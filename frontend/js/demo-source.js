// DemoSource: a scripted demo call. The server plays the script and ends the
// call when it is over, so there is no audio to capture or send here. Same
// interface as MicCapture and FileSource, so the rest of the page doesn't care.

export class DemoSource {
  constructor(demoCall) {
    this.demoCall = demoCall; // { id, title, ... } from /api/demo-calls
  }

  get label() {
    return `Demo: ${this.demoCall.title}`;
  }

  async prepare() {}

  async start() {}

  stop() {}
}
