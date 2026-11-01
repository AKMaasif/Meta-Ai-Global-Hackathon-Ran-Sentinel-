# py scripts\check_google_tts.py
import base64, glob, json, os, re, sys, urllib.error, urllib.request, wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = "Hello Jordan. Your data connection looks healthy. Signal is good at your home address."


def find_key():
    if os.environ.get("GOOGLE_API_KEY"):
        return os.environ["GOOGLE_API_KEY"].strip(), "environment"
    env = os.path.join(ROOT, ".env")
    if os.path.exists(env):
        for line in open(env, encoding="utf-8"):
            if line.startswith("GOOGLE_API_KEY=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip().strip('"'), ".env"
    for path in glob.glob(os.path.join(os.path.dirname(ROOT), "*oogle*.txt")) + glob.glob(os.path.join(ROOT, "*oogle*.txt")):
        m = re.search(r"AIza[0-9A-Za-z_\-]{30,}", open(path, encoding="utf-8", errors="ignore").read())
        if m:
            return m.group(0), os.path.basename(path)
    return None, None


def call(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        return e.code, {"error": msg}
    except Exception as e:
        return 0, {"error": str(e)}


def gemini(key):
    print("\n[1] Gemini API")
    code, d = call(f"https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key={key}")
    if code != 200:
        print(f"  FAIL listing models (HTTP {code}): {d.get('error')}")
        return False
    names = [m["name"].split("/")[-1] for m in d.get("models", [])]
    tts = [n for n in names if "tts" in n]
    live = [n for n in names if "live" in n or "native-audio" in n]
    print(f"  key works, {len(names)} models visible")
    print(f"  TTS models: {', '.join(tts) or 'none'}")
    print(f"  Live / native-audio models: {', '.join(live) or 'none'}")
    ok = False
    for model in tts:
        code, d = call(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}", {
            "contents": [{"parts": [{"text": SAMPLE}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}}}})
        try:
            pcm = base64.b64decode(d["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
        except Exception:
            print(f"  FAIL {model} (HTTP {code}): {d.get('error') or 'no audio returned'}")
            continue
        out = os.path.join(ROOT, "data", f"google_tts_{model}.wav")
        with wave.open(out, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
        print(f"  PASS {model}: {len(pcm) / 48000:.1f} s of speech -> {out}")
        ok = True
    return ok


def cloud_tts(key):
    print("\n[2] Cloud Text-to-Speech API")
    code, d = call(f"https://texttospeech.googleapis.com/v1/voices?languageCode=en-US&key={key}")
    if code != 200:
        print(f"  FAIL (HTTP {code}): {d.get('error')}")
        print("  (If it says the API is disabled, enable 'Cloud Text-to-Speech API' for this key's project.)")
        return False
    voices = [v["name"] for v in d.get("voices", [])]
    print(f"  {len(voices)} en-US voices, e.g. {', '.join(voices[:5])}")
    code, d = call(f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}", {
        "input": {"text": SAMPLE}, "voice": {"languageCode": "en-US"}, "audioConfig": {"audioEncoding": "MP3"}})
    if "audioContent" not in d:
        print(f"  FAIL synthesize (HTTP {code}): {d.get('error')}")
        return False
    out = os.path.join(ROOT, "data", "google_tts_cloud.mp3")
    open(out, "wb").write(base64.b64decode(d["audioContent"]))
    print(f"  PASS synthesize -> {out}")
    return True


if __name__ == "__main__":
    key, src = find_key()
    if not key:
        sys.exit("No Google key found. Put GOOGLE_API_KEY=... in the .env file in the project folder or save it in 'google api key.txt'.")
    print(f"Using Google key from {src} (length {len(key)}, ends ...{key[-4:]})")
    a, b = gemini(key), cloud_tts(key)
    print("\nRESULT:", "TTS AVAILABLE" if (a or b) else "NO TTS with this key",
          f"(Gemini TTS: {'yes' if a else 'no'}, Cloud TTS: {'yes' if b else 'no'})")
