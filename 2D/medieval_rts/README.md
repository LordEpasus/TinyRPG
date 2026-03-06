# Medieval Kingdoms RTS - GitHub ve EXE dagitim akisi

Bu proje iki yoldan dagitiliyor:
- Gelistirme ekibi: GitHub uzerinden `clone` ve `pull`
- Oyuncular: GitHub Releases uzerinden hazir Windows paketini indirir

## Hizli komutlar

### 1) Sifirdan klonla

```bash
git clone https://github.com/LordEpasus/TinyRPG.git
cd TinyRPG
git checkout main
```

### 2) Guncel kodu cek

```bash
cd TinyRPG
git pull origin main
```

### 3) Vendor assetleri projeye kopyala

`settings.py` once `assets/vendor2d` klasorunu arar. EXE build oncesi bu klasorun dolu olmasi gerekir.

```bash
cd TinyRPG/2D/medieval_rts
python3 scripts/sync_vendor_assets.py --clean
```

Bu komut su paketleri `assets/vendor2d/` altina toplar:
- Tiny Swords (Free Pack)
- mystic_woods_free_2
- Pixel Art Top Down - Basic v1
- Sprout Lands - Sprites - Basic pack
- Tiny RPG Character Asset Pack v1.03 -Free Soldier&Orc
- Ship_full.png

### 4) Lokal Windows EXE build

Windows tarafinda:

```powershell
cd TinyRPG\2D\medieval_rts
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python scripts/build_windows_exe.py --clean
```

Uretilen cikti:
- `2D/medieval_rts/release/MedievalKingdomsRTS-win64.zip`

Zip icinde:
- `MedievalKingdomsRTS.exe` -> launcher / auto updater
- `runtime/` -> asil oyun dosyalari
- `version.txt` -> paket surumu

### 5) GitHub Release cikar

`main` branch guncel olduktan sonra surumu guncelleyip tag push etmemiz yeterli:

```bash
cd TinyRPG
git checkout main
git pull origin main
cd 2D/medieval_rts
# version.py icindeki VERSION degerini artir
cd ../..
git tag v0.1.0
git push origin main --tags
```

Workflow dosyasi:
- `.github/workflows/medieval-rts-release.yml`

Bu workflow Windows runner acip zip dosyasini otomatik release olarak yukler.

## Arkadaslar nasil gunceller?

### Gelistirici arkadaslar

```bash
git pull origin main
```

### Oyuncu arkadaslar

- GitHub repo icindeki **Releases** sayfasina girer.
- Son surum `MedievalKingdomsRTS-win64.zip` dosyasini indirir.
- Zip'i acip `MedievalKingdomsRTS.exe` dosyasini calistirir.
- Launcher acilista GitHub latest release kontrolu yapar.
- Yeni surum varsa indirip dosyalari gunceller ve oyunu tekrar baslatir.

## Not

Bu monorepo icinde Git tarafinda yalnizca `2D/medieval_rts` ve `.github/workflows` takip edilecek sekilde kok `.gitignore` ayarlanmistir.
