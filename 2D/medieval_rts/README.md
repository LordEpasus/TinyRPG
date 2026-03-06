# Medieval Kingdoms RTS - GitHub + EXE dagitim akisi

Bu proje artik su sekilde dagitilabilir:
- Gelistirme: GitHub repo uzerinden `git pull`
- Oyuncu dagitimi: GitHub Releases uzerinden Windows `.exe` zip

## 1) Ilk kurulum (developer)

Repo koku: `/Users/mustafasalepci/Projeler`

```bash
cd /Users/mustafasalepci/Projeler
# ilk defa remote eklemek icin
# git remote add origin <GITHUB_REPO_URL>
```

Bu repoda sadece `2D/medieval_rts` ve `.github/workflows` takip edilecek sekilde `.gitignore` ayarlandi.

## 2) Vendor assetleri proje icine cek (exe icin zorunlu)

`settings.py`, once `assets/vendor2d` klasorunu arar. Varsa buradan calisir.

```bash
cd /Users/mustafasalepci/Projeler/2D/medieval_rts
python3 scripts/sync_vendor_assets.py --clean
```

Bu komut asagidaki dis paketleri `assets/vendor2d/` altina kopyalar:
- Tiny Swords (Free Pack)
- mystic_woods_free_2
- Pixel Art Top Down - Basic v1
- Sprout Lands - Sprites - Basic pack
- Tiny RPG Character Asset Pack v1.03 -Free Soldier&Orc
- Ship_full.png

## 3) Lokal Windows exe build

Windows'ta:

```powershell
cd 2D/medieval_rts
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python scripts/build_windows_exe.py --clean
```

Cikti:
- `2D/medieval_rts/release/MedievalKingdomsRTS-win64.zip`

## 4) Otomatik GitHub Release

Tag push yapildiginda GitHub Actions otomatik build + release yapar:

```bash
cd /Users/mustafasalepci/Projeler
git tag v0.1.0
git push origin master --tags
```

Workflow dosyasi:
- `.github/workflows/medieval-rts-release.yml`

## 5) Arkadaslar guncelleme nasil alacak?

### A) Gelistirici arkadaslar
```bash
git pull
```

### B) Oyuncu arkadaslar
- GitHub repo > **Releases** > son surum `MedievalKingdomsRTS-win64.zip`
- Zip'i indirip acar, `MedievalKingdomsRTS.exe` calistirir.
- Yeni surumde tekrar latest release indirir.

---

Istersen bir sonraki adimda otomatik "in-game update checker" da ekleriz (GitHub latest release API kontrolu).
