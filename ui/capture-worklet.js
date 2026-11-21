// Posts ~100 ms blocks of mono float samples; the context runs at 24 kHz so no resampling is needed here.
class Capture extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2400); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.buf[this.n++] = ch[i];
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
    }
    return true;
  }
}
registerProcessor('capture', Capture);
