// Browser-side audio: anything the browser can decode -> 16 kHz mono 16-bit WAV (what the server wants).

export async function toWav16k(blob: Blob, lastSeconds?: number): Promise<Blob> {
  const ac = new AudioContext();
  const buf = await ac.decodeAudioData(await blob.arrayBuffer());
  ac.close();
  const off = new OfflineAudioContext(1, Math.ceil(buf.duration * 16000), 16000);
  const src = off.createBufferSource(); src.buffer = buf; src.connect(off.destination); src.start();
  let data = (await off.startRendering()).getChannelData(0);
  if (lastSeconds) data = data.subarray(Math.max(0, data.length - lastSeconds * 16000));
  const n = data.length, ab = new ArrayBuffer(44 + n * 2), v = new DataView(ab);
  const ws = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  ws(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); ws(8, "WAVEfmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 16000, true); v.setUint32(28, 32000, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); ws(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, data[i])) * 32767, true);
  return new Blob([ab], { type: "audio/wav" });
}

/** Calls onLevel(0..1) ~20x/s with the stream's peak level; returns a stop function. */
export function watchLevel(stream: MediaStream, onLevel: (v: number) => void): () => void {
  const ctx = new AudioContext();
  const an = ctx.createAnalyser(); an.fftSize = 512;
  ctx.createMediaStreamSource(stream).connect(an);
  const buf = new Uint8Array(an.fftSize);
  const id = setInterval(() => {
    an.getByteTimeDomainData(buf);
    let peak = 0; for (const x of buf) peak = Math.max(peak, Math.abs(x - 128));
    onLevel(Math.min(1, peak / 90));
  }, 50);
  return () => { clearInterval(id); ctx.close(); };
}
