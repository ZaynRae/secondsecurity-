# giveaway-grok

Tool CLI Python untuk auto-generate komentar/kalimat ikut giveaway dengan
**gaya bahasa "Grok-style"** yang dipakai di repo
[xai-org/x-algorithm](https://github.com/xai-org/x-algorithm) — yaitu:

- System prompt imperatif (contoh: `Analyze ... Provide the requested JSON object`)
- Suhu sampling sangat rendah (`temperature = 0.000001`) supaya deterministik
- Output dibungkus tag `<json>...</json>` lalu diparse dengan regex
  `r"(.*?)<json>(.*?)</json>"` — mirip `result_pattern` di
  `grox/classifiers/content/banger_initial_screen.py`

## Cara kerja singkat

1. Kamu kirim teks postingan giveaway (lewat argumen, file, atau stdin).
2. Tool membangun pesan dua peran:
   - `system` → aturan output ketat dalam bahasa Inggris imperatif.
   - `user`   → `Analyze the giveaway post above and provide the requested JSON object.`
3. Memanggil **xAI Chat Completions API** kalau `XAI_API_KEY` tersedia.
4. Memparse blok `<json>` dan menampilkan beberapa varian komentar siap-paste.
5. Jika tidak ada API key atau pakai flag `--offline`, jatuh ke generator
   template lokal yang tetap mengikuti kontrak output yang sama.

## Pemakaian

```bash
# 1. Via env var (xAI API)
export XAI_API_KEY=xai-xxxxxxxx
python giveaway_grok.py "Giveaway 1 iPhone 15! RT + follow @akun + comment alasanmu"

# 2. Baca teks dari file
python giveaway_grok.py -f post.txt -n 5

# 3. Pipe lewat stdin
echo "Giveaway saldo dana 500rb..." | python giveaway_grok.py -

# 4. Mode offline (tanpa internet / API key)
python giveaway_grok.py --offline "Giveaway tumbler eksklusif..."

# 5. Tampilkan output mentah (reasoning + <json>...</json>)
python giveaway_grok.py --raw "Giveaway PS5..."
```

## Opsi CLI

| Flag | Default | Keterangan |
|------|---------|------------|
| `post` (positional) | – | Teks postingan giveaway. Pakai `-` untuk stdin. |
| `-f, --file PATH`   | – | Baca teks giveaway dari file. |
| `-n, --num N`       | `3` | Jumlah varian komentar (1..10). |
| `--model NAME`      | `grok-4-latest` (atau `XAI_MODEL`) | Nama model xAI. |
| `--offline`         | off | Paksa pakai generator template lokal. |
| `--raw`             | off | Cetak output mentah, jangan diparse. |

## Output

```
Detected language : id
Detected prize    : Giveaway 1 iPhone 15
Detected host     : @akun

Reasoning:
  Bahasa terdeteksi: id. Prize tebakan: 'Giveaway 1 iPhone 15'. ...

Generated comments:
  1. Ikutan ya kak! Giveaway 1 iPhone 15 banget bisa bikin produktif kerja...
  2. Wah Giveaway 1 iPhone 15 idamanku banget 🤞 udah follow + RT, fingers crossed!
  3. Done semua syarat @akun! Kalau menang aku mau dipake kerja remote...
```

## Catatan etika

- Tool ini **bukan untuk spam**. Selalu pertimbangkan aturan giveaway
  (tidak boleh akun bot, tidak boleh komentar berulang, dst).
- Tool **tidak** memalsukan data pribadi (jumlah follower, history pembelian,
  identitas, dsb) — system prompt secara eksplisit melarang ini.
- Pakai dengan tanggung jawab kamu sendiri.
