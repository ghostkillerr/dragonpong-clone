"""Copy user-owned local working files and document them; never downloads assets."""
import hashlib
import json
import shutil
import wave
from pathlib import Path

BASE = Path(__file__).resolve().parent
SOURCE = BASE.parent / 'Sounds'
DEST = BASE / 'reference_sounds' / 'Sounds'


def role(relative):
    folder, name = relative.split('/')[0], Path(relative).stem.lower()
    exact = {'rolling': 'Topun devamlı hareket sesi', 'ballborder': 'Topun yan duvara çarpması',
             'border': 'Oyuncunun saha sınırına dayanması', 'move': 'Oyuncu adımı',
             'hit': 'Servis ve raket vuruşu', 'shieldon': 'Kalkan kazanma',
             'shieldloop': 'Etkin kalkan döngüsü', 'shieldhit': 'Kalkanın topu geri çevirmesi',
             'shieldoff': 'Kalkan süresinin dolması', 'appear': 'Sessiz topun yeniden duyulması',
             'disappear': 'Sessiz topun başlaması', 'game_won': 'Maç kazanma müziği',
             'game_lost': 'Maç kaybetme müziği'}
    if folder in ('Pong', 'Misc', 'Music') and name in exact:
        return exact[name], 'EXE ses yükleyicisi ve olay çağrıları'
    if folder == 'Chars':
        kind = ('Rakip gol atınca tepki' if name.startswith('opscore') else
                'Gol atınca tepki' if name.startswith('score') else
                {'name': 'Karakter adı', 'intro': 'Karakter giriş repliği',
                 'win': 'Karakter kazanma repliği', 'lose': 'Karakter kaybetme repliği'}.get(name, name))
        return f'Karakter {relative.split("/")[1]}: {kind}', 'EXE ses yükleyicisi; bütün zamanlamalar henüz doğrulanmadı'
    if folder == 'Pong' and name.startswith('goal'):
        return 'Gol efekti varyantı', 'Goal1..8 yükleniyor; Goal.wav kullanımı henüz doğrulanmadı'
    if folder == 'announcer':
        return f'Anons: {name}', 'Dosya adı; sayılar 0..21, yüksek skorlar için kayıt yok'
    return f'{folder} / {name}', 'Dosya adı; tam olay sırası henüz doğrulanmadı'


def main():
    entries = []
    for source in sorted(SOURCE.rglob('*.wav')):
        relative = source.relative_to(SOURCE).as_posix()
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise RuntimeError(f'Yerel değiştirilmiş dosya üzerine yazılmadı: {target}')
        shutil.copy2(source, target)
        with wave.open(str(source), 'rb') as sound:
            duration = sound.getnframes() / sound.getframerate()
            rate, channels = sound.getframerate(), sound.getnchannels()
        description, evidence = role(relative)
        entries.append(dict(file=relative, role=description, evidence=evidence,
                            seconds=round(duration, 4), rate=rate, channels=channels,
                            sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    (BASE / 'reference_sounds' / 'manifest.json').write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Yerel ses rehberi', '',
             'Bu 143 dosya özgün oyundan yerel karşılaştırma için kopyalandı. MIT lisansına dahil değildir.',
             'Dosyaları aynı yoldaki WAV ile değiştirip oyunu yeniden açabilirsin. Kaynak dosyalar değiştirilmez.',
             'Olay efektleri ve top döngüsü bağlıdır. Diğer dosyaların varlığı, tüm olay sıralarının eşdeğerliğini kanıtlamaz.', '',
             '| Dosya | Anlamı | Süre | Eşleme kanıtı |', '|---|---|---:|---|']
    for entry in entries:
        lines.append(f"| [\u200b{entry['file']}](Sounds/{entry['file']}) | {entry['role']} | {entry['seconds']} sn | {entry['evidence']} |")
    (BASE / 'reference_sounds' / 'SESLER.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'{len(entries)} sounds copied; manifest and SESLER.md written')


if __name__ == '__main__':
    main()
