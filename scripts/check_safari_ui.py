"""Safari UI check on macOS, with an isolated offline app and no hardware microphone."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

ROOT = Path(__file__).resolve().parents[1]


def main():
    passed = []
    def check(label, condition=True):
        if not condition:
            raise AssertionError(label)
        passed.append(label)
        print('PASS: ' + label, flush=True)

    with tempfile.TemporaryDirectory(prefix='ran-sentinel-safari-') as folder:
        work = Path(folder)
        for name in ('backend', 'frontend'):
            shutil.copytree(ROOT / name, work / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(ROOT / 'run.py', work / 'run.py')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, MODEL_API_KEY='', GOOGLE_API_KEY='', FIREWORKS_API_KEY='', MAVERIC_URL='',
                   OPS_EMAIL='ops@northstar.demo', OPS_PASSWORD='sentinel-demo',
                   CUSTOMER_EMAIL='customer@northstar.demo', CUSTOMER_PASSWORD='connect-demo')
        browser = None
        with (work / 'server.log').open('w+') as log:
            server = subprocess.Popen([sys.executable, str(work / 'run.py'), '--port', str(port)], cwd=work,
                                      env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                until = time.monotonic() + 90
                while time.monotonic() < until:
                    try:
                        if httpx.get(base + '/ops/', timeout=2).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.5)
                else:
                    raise RuntimeError('Local server did not start')
                browser = webdriver.Safari()
                browser.set_script_timeout(30)
                browser.set_window_size(1440, 1000)
                wait = WebDriverWait(browser, 30)
                def click(by, value):
                    def attempt(driver):
                        try:
                            element = driver.find_element(by, value)
                            if not element.is_displayed() or not element.is_enabled():
                                return False
                            element.click()
                            return True
                        except WebDriverException:
                            return False
                    wait.until(attempt)
                print('Browser:', browser.capabilities.get('browserName'), browser.capabilities.get('browserVersion'), flush=True)
                browser.get(base + '/ops/')
                wait.until(EC.visibility_of_element_located((By.ID, 'email'))).send_keys('ops@northstar.demo')
                browser.find_element(By.ID, 'pw').send_keys('sentinel-demo')
                click(By.CSS_SELECTOR, '.form button')
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.shell')))
                check('engineer sign-in and console render in Safari')
                check('engineer search control is available', browser.find_element(By.ID, 'gq').is_displayed())
                browser.get(base + '/connect/#/login')
                wait.until(EC.visibility_of_element_located((By.ID, 'em'))).send_keys('customer@northstar.demo')
                browser.find_element(By.ID, 'pw').send_keys('connect-demo')
                click(By.CSS_SELECTOR, '#f button')
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.app')))
                check('customer sign-in and navigation render in Safari')
                supported = browser.execute_script('return !!(window.MediaRecorder && navigator.mediaDevices?.getUserMedia && (window.AudioContext || window.webkitAudioContext));')
                check('Safari exposes the recording and Web Audio APIs', supported)
                browser.execute_script("""
                    window.__safariCapture = null;
                    const button = document.createElement('button');
                    button.id = 'safari-audio-fixture'; button.textContent = 'Check audio capture';
                    button.style.cssText = 'position:fixed;top:5px;left:5px;z-index:999999';
                    button.onclick = async () => {
                        const original = navigator.mediaDevices.getUserMedia;
                        let source;
                        navigator.mediaDevices.getUserMedia = async () => {
                            const Ctx = window.AudioContext || window.webkitAudioContext;
                            source = new Ctx();
                            const output = source.createMediaStreamDestination();
                            const tone = source.createOscillator(), volume = source.createGain();
                            volume.gain.value = 0.25;
                            tone.connect(volume); volume.connect(output);
                            await source.resume();
                            tone.start(source.currentTime + 0.5); tone.stop(source.currentTime + 1.5);
                            return output.stream;
                        };
                        try {
                            const session = await UI.listen({silenceMs:400, maxSeconds:4, waitSeconds:4});
                            const wav = await session.result;
                            if (!wav) throw new Error('No synthetic voice detected');
                            const bytes = await wav.arrayBuffer(), view = new DataView(bytes);
                            window.__safariCapture = {header:String.fromCharCode(...new Uint8Array(bytes,0,4)),
                                rate:view.getUint32(24,true), channels:view.getUint16(22,true), bytes:bytes.byteLength};
                        } catch (error) { window.__safariCapture = {error:error.message}; }
                        finally { navigator.mediaDevices.getUserMedia = original; if (source) await source.close(); button.remove(); }
                    };
                    document.body.appendChild(button);
                """)
                click(By.ID, 'safari-audio-fixture')
                capture = wait.until(lambda d: d.execute_script('return window.__safariCapture'))
                check('synthetic input passes Safari recording, silence detection and 16 kHz WAV conversion',
                      capture.get('header') == 'RIFF' and capture.get('rate') == 16000 and capture.get('channels') == 1 and capture.get('bytes', 0) > 44)
                # UI tests keep speech silent; audibility requires a separate listening check.
                browser.execute_script('''if (window.speechSynthesis) {
                    speechSynthesis.cancel = () => {};
                    speechSynthesis.getVoices = () => [];
                    speechSynthesis.speak = u => setTimeout(() => u.onend && u.onend(), 0);
                }''')
                click(By.ID, 'valaunch')
                def ask(text):
                    field = wait.until(EC.visibility_of_element_located((By.ID, 'vaq')))
                    field.clear()
                    field.send_keys(text)
                    click(By.CSS_SELECTOR, '#vaask button')
                    wait.until(lambda d: text in d.find_element(By.ID, 'vasay').text and
                               d.find_element(By.ID, 'vastatus').text.startswith('Tap the mic'))
                def current_id():
                    return wait.until(lambda d: d.execute_script("return document.querySelector('[data-vconfirm]')?.getAttribute('data-vconfirm');"))
                ask('My data is slow at work')
                ask('Report that')
                old = current_id()
                check('contextual complaint draft opens at Work', browser.execute_script("return document.querySelector('input[name=place]:checked')?.value") == 'work')
                ask('Actually, change the location to home')
                revised = current_id()
                check('correction replaces the approval and updates the location', revised != old and browser.execute_script("return document.querySelector('input[name=place]:checked')?.value") == 'home')
                browser.refresh()
                wait.until(lambda d: d.execute_script("return document.querySelector('input[name=place]:checked')?.value") == 'home')
                click(By.ID, 'valaunch')
                check('refresh restores the complaint and approval', current_id() == revised)
                ask('Read it back')
                check('draft read-back uses the revised location', 'home' in browser.find_element(By.ID, 'vasay').text.lower())
                ask('Yes, send it')
                check('later confirmation submits the complaint', 'sent report' in browser.find_element(By.ID, 'vasay').text)
                ask('Yes please')
                check('another yes cannot submit the complaint twice', 'No change was made' in browser.find_element(By.ID, 'vasay').text)
                click(By.ID, 'vanew')
                wait.until(lambda d: 'Conversation cleared' in d.find_element(By.ID, 'vasay').text)
                ask('Report that')
                check('New conversation clears old references', len(browser.find_elements(By.CSS_SELECTOR, '[data-vconfirm]')) == 0)
                check('customer layout fits its viewport', browser.execute_script('return document.documentElement.scrollWidth <= innerWidth + 1'))
                print(f'All {len(passed)} native Safari checks passed.', flush=True)
                return 0
            except Exception:
                log.flush()
                print((work / 'server.log').read_text()[-3000:], file=sys.stderr)
                raise
            finally:
                if browser:
                    browser.quit()
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == '__main__':
    raise SystemExit(main())
