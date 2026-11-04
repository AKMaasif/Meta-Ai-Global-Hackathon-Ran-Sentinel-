/* Speech output stays on the device. Never select a remote browser voice. */
window.LocalSpeech = (() => {
  const synth = window.speechSynthesis;
  const listeners = new Set();
  let active = null, generation = 0;

  function voices() {
    return (synth?.getVoices() || []).filter((v) => v.localService === true && /^en(?:[-_]|$)/i.test(v.lang))
      .sort((a, b) => Number(/zira|samantha|karen|serena|victoria/i.test(b.name)) - Number(/zira|samantha|karen|serena|victoria/i.test(a.name)) || a.name.localeCompare(b.name));
  }
  synth?.addEventListener("voiceschanged", () => listeners.forEach((fn) => fn()));

  function cancel() {
    generation++;
    if (active) active({ cancelled: true });
    synth?.cancel();
  }

  async function say(text, { voiceURI } = {}) {
    cancel();
    const turn = generation;
    if (voiceURI === "off") return { note: "Text only. Choose a local voice to hear replies." };
    if (!synth || !window.SpeechSynthesisUtterance) return { note: "Speech is unavailable in this browser. Read the reply above." };
    if (!voices().length) {
      await new Promise((resolve) => {
        const finish = () => { clearTimeout(timer); synth.removeEventListener("voiceschanged", finish); if (active === finish) active = null; resolve(); };
        const timer = setTimeout(finish, 600);
        active = finish;
        synth.addEventListener("voiceschanged", finish);
      });
    }
    if (turn !== generation) return { cancelled: true };
    const available = voices();
    const voice = available.find((v) => v.voiceURI === voiceURI) || available[0];
    if (!voice) return { note: "No local English voice is available. Read the reply, or install an English system voice and reopen the app." };
    return new Promise((resolve) => {
      let finished = false;
      const utterance = new SpeechSynthesisUtterance(text);
      const finish = (result = {}) => {
        if (finished) return;
        finished = true; clearTimeout(timer);
        utterance.onend = utterance.onerror = null;
        if (active === finish) active = null;
        resolve(result);
      };
      const timer = setTimeout(() => { finish({ note: "Speech stopped. You can read the complete reply above." }); synth.cancel(); }, 5000 + text.split(/\s+/).length * 800);
      active = finish;
      utterance.voice = voice;
      utterance.lang = voice.lang;
      utterance.rate = 1;
      utterance.onend = () => finish();
      utterance.onerror = () => finish({ note: "Speech could not play. Read the reply above, or try another local voice." });
      try { synth.speak(utterance); }
      catch { finish({ note: "Speech could not start. Read the reply above." }); }
    });
  }

  return { voices, say, cancel, subscribe: (fn) => listeners.add(fn) };
})();
