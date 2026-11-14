# Arık Makro

Windows için profilli, global kısayollu ve piksel izlemeli masaüstü makro
uygulaması.

## Çalıştırma

Proje kökündeki `baslat.bat` dosyasına çift tıklayın. Python 3.10 veya daha yenisini bilgisayarınıza bir kez kurun. Başlatıcı mevcut Python
kurulumunu seçer, eksik bağımlılıkları yükler ve uygulamayı konsolsuz açar.

Terminalden çalıştırmak için:

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m kodlar.main
```

Sistem ilk açılışta pasiftir. `settings.ini` içindeki kısayol veya orta fare
tuşu sistemi başlatıp durdurur.

## Özellikler

- Birden çok makro profili
- Klavye ve fare tetikleme
- Sabit fare hedefi seçimi
- Piksel rengi farklı kaldığı sürece belirtilen aralıkla tetikleme; her basış öncesi renk kontrolü
- Rastgele ek gecikme
- Global başlatma/durdurma kısayolu
- Arayüzden tek tıkla başlatma/durdurma
- Yan fare tuşları (X1/X2) desteği
- Süreli, sıralı ve iç içe çalışma grupları
- Atomik profil ve ayar kaydı
- Kurulum klasöründen bağımsız `%APPDATA%\ArikMakro` profil saklama
- Önceki LocalAppData ve taşınabilir sürümlerden otomatik profil göçü
- Dönen `app.log` hata kayıtları

## Sıralı gruplar

1. `Yeni Grup Ekle` ile bir grup oluşturun.
2. Grup üzerindeki `İçine Tuş` ve `İçine Grup` düğmeleriyle adımları ekleyin.
3. Adımlar arasındaki `sn bekle` alanına geçiş süresini yazın.
4. Ana `BAŞLAT` düğmesine basın; tüm ana gruplar otomatik başlar.

Adımlar yukarıdan aşağıya etkinleşir. Alt grup tek bir adım gibi çalışır ve
kendi içindeki sıra tamamlandıktan sonra ana grup bir sonraki adıma geçer.

## Mimari

- `main.py`: uygulama yaşam döngüsü ve hata kaydı
- `gui.py`: Tkinter arayüzü
- `ui_widgets.py`: tema ve tekrar kullanılabilir arayüz bileşenleri
- `engine.py`: global giriş dinleyicileri ve worker yönetimi
- `workers.py`: klavye, fare ve piksel izleme worker'ları
- `sequences.py`: iç içe grup veri modeli ve profil serileştirme
- `sequence_runner.py`: iptal edilebilir sıralı grup yürütücüsü
- `models.py`: veri modelleri, doğrulama ve eski profil dönüşümü
- `profile_store.py`: güvenli JSON okuma/yazma
- `platform_win.py`: DPI ve Win32 piksel erişimi
- `config.py`: uygulama ayarları
- `clicker.py`: eski içe aktarımlar için uyumluluk katmanı

## Testler

Proje kökünde şu komutu çalıştırın:

```powershell
py -3 -m unittest discover -s kodlar/tests -v
```

Geliştirme kurulumu için isteğe bağlı olarak:

```powershell
py -3 -m pip install -e .
arik-makro
```

## Sorun giderme

Uygulama açılmazsa `app.log` dosyasını kontrol edin. Bazı oyunlar sentetik
girişleri engelleyebilir; bu durumda uygulama ile hedef programın yetki
seviyelerinin aynı olması gerekir.
