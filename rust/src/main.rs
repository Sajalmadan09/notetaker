//! Spike: run the int4 FastConformer encoder via the ort crate (same ONNX Runtime
//! kernels as Python) and verify parity + speed. Usage:
//!   notetaker-spike feats.npy hidden_ref.npy encoder.onnx audio_seconds
use std::env;
use std::time::Instant;

use ort::session::Session;
use ort::value::Value;

fn read_npy(path: &str) -> (Vec<usize>, Vec<f32>) {
    let b = std::fs::read(path).unwrap();
    assert_eq!(&b[0..6], b"\x93NUMPY");
    let hlen = u16::from_le_bytes([b[8], b[9]]) as usize;
    let header = String::from_utf8_lossy(&b[10..10 + hlen]).to_string();
    let shape_str = header
        .split("'shape': (")
        .nth(1)
        .unwrap()
        .split(')')
        .next()
        .unwrap();
    let shape: Vec<usize> = shape_str
        .split(',')
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .map(|s| s.parse().unwrap())
        .collect();
    let data = &b[10 + hlen..];
    let raw: Vec<f32> = data
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect();
    // np.save preserves Fortran order; the tensor API wants C order.
    if header.contains("'fortran_order': True") {
        assert_eq!(shape.len(), 3);
        let (s0, s1, s2) = (shape[0], shape[1], shape[2]);
        let mut vals = vec![0f32; raw.len()];
        for k in 0..s2 {
            for j in 0..s1 {
                for i in 0..s0 {
                    vals[(i * s1 + j) * s2 + k] = raw[i + s0 * (j + s1 * k)];
                }
            }
        }
        (shape, vals)
    } else {
        (shape, raw)
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    let (shape, feats) = read_npy(&args[1]);
    let (_, reference) = read_npy(&args[2]);
    let audio_s: f64 = args[4].parse().unwrap();

    let environment = ort::environment::init().build()?;
    let mut session = Session::builder(&environment)?
        .with_intra_threads(1)?
        .with_optimization_level(ort::session::builder::GraphOptimizationLevel::All)?
        .with_memory_pattern(true)?
        .commit_from_file(&args[3])?;
    let t0 = Instant::now();
    let shape_i64: Vec<i64> = shape.iter().map(|&d| d as i64).collect();
    let input = Value::from_array((shape_i64, feats))?;
    let (hshape_vec, h): (Vec<usize>, Vec<f32>) = {
        let outputs = session.run(ort::inputs!["feats" => input])?;
        let hidden = outputs["hidden"].try_extract_tensor::<f32>()?;
        let (hshape, hslice) = hidden;
        println!("ort=load-dynamic hidden_shape={:?} len={} ref_len={}",
                 hshape, hslice.len(), reference.len());
        (hshape.iter().map(|&d| d as usize).collect(), hslice.to_vec())
    };
    if args.len() > 5 {
        let header = format!(
            "{{'descr': '<f4', 'fortran_order': False, 'shape': ({}, {}, {}), }}",
            hshape_vec[0], hshape_vec[1], hshape_vec[2]);
        let pad = 64 - ((10 + header.len() + 1) % 64);
        let header = format!("{}{}\n", header, " ".repeat(pad));
        let mut out = Vec::new();
        out.extend_from_slice(b"\x93NUMPY");
        out.extend_from_slice(&[1, 0]);
        out.extend_from_slice(&(header.len() as u16).to_le_bytes());
        out.extend_from_slice(header.as_bytes());
        for v in &h {
            out.extend_from_slice(&v.to_le_bytes());
        }
        std::fs::write(&args[5], out)?;
    }
    let wall = t0.elapsed().as_secs_f64();
    let t1 = Instant::now();
    let shape_i64_2: Vec<i64> = shape.iter().map(|&d| d as i64).collect();
    let (_, feats2) = read_npy(&args[1]);
    let input2 = Value::from_array((shape_i64_2, feats2))?;
    let _ = session.run(ort::inputs!["feats" => input2])?;
    println!("warm second run: {:.3}s", t1.elapsed().as_secs_f64());
    let dot: f64 = h.iter().zip(&reference).map(|(a, b)| f64::from(*a) * f64::from(*b)).sum();
    let na: f64 = h.iter().map(|a| f64::from(*a) * f64::from(*a)).sum::<f64>().sqrt();
    let nb: f64 = reference.iter().map(|a| f64::from(*a) * f64::from(*a)).sum::<f64>().sqrt();
    println!(
        "rust encoder: cosine={:.6} wall={:.3}s rtf={:.2} (shape {:?})",
        dot / (na * nb),
        wall,
        audio_s / wall,
        shape
    );
    Ok(())
}
