# Arık Makro

Windows için profilli, global kısayollu ve piksel izlemeli masaüstü makro
uygulaması.

## Çalıştırma

Proje kökündeki `baslat.bat` dosyasına çift tıklayın. Python 3.10 veya daha yenisini bilgisayarınıza bir kez kurun. Başlatıcı mevcut Python
kurulumunu seçer ve eksik bağımlılıkları yükler. Normal açılışta komut
penceresi kapanır. Açılış hataları bir ileti kutusunda gösterilir ve
`%APPDATA%\ArikMakro\startup-error.log` dosyasına kaydedilir.
Konsolda ayrıntılı inceleme için `py kodlar/hata_ayikla.py` komutunu çalıştırın.

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

## Profilleri temizleme

Dağıtım boş bir Varsayılan profiliyle gelir. Daha önce bilgisayara kaydedilmiş
profilleri, grupları ve atamaları silmek için profil satırındaki `Sıfırla`
düğmesini kullanın. Onaydan sonra makrolar durur ve başlat/durdur kısayolu
ESC olur. Profil kurtarma yedeği de boşaltılır.

## Güncellemeler

Windows ZIP kurulumu açılışta GitHub Releases üzerindeki en son sürümü kontrol eder.
Yeni paket HTTPS üzerinden indirilir ve SHA-256 özeti doğrulanır. Ana sistem
pasifken otomatik uygulanır ve uygulama yeniden açılır; çalışan makrolar kesilmez.
Profiller, ayarlar ve sanal ortam korunur. İnternet yoksa uygulama çalışmaya devam eder.
Bağımlılıklar değişmişse normal ZIP kurulumu gerekir; durum kayıtlarda belirtilir.
Git çalışma kopyalarında otomatik dosya değiştirme kapalıdır.

Profil işlemleri profil satırındaki `⋯` menüsündedir. Gruplar yalnızca ana
`BAŞLAT` ile başlatılır; her kök grup kendi iç sırasını yürütür.

`main` dalına gönderilen değişiklikler GitHub Actions ile `2.1.<çalışma numarası>`
sürümü olarak yayımlanır. İndirilecek dosya Releases içindeki `arik-makro.zip`tir.
İlk otomatik güncellemeli sürüm bir kez elle kurulmalıdır. Actions ve yayınlama
izinlerinin GitHub üzerinde etkin olması gerekir.

## Paket düzeni

İndirilecek `arik-makro.zip` paketinin ana klasöründe yalnızca `baslat.bat` ve
`kodlar` bulunur. Sanal ortam da `kodlar/.venv` altında oluşturulur.
Yeni düzeni kullanmak için ZIP'i boş bir klasöre çıkarın; eski klasörün üzerine
çıkarmak eski sürüm dosyalarını silmez. Kullanıcı profilleri uygulama klasörü
dışındaki AppData alanında saklandığı için yeni klasörde de korunur.
GitHub'ın kaynak kod ZIP'i geliştirme dosyalarını içerir; uygulama paketi için
Releases içindeki `arik-makro.zip` dosyasını indirin.

Sol tıklama aralığı en az `0.050` saniyedir. Daha küçük değerler, eski profiller
yüklendiğinde ve zamanlama alanı kaydedildiğinde uyarı verilmeden bu değere çekilir.
Bu değer bekleme aralığıdır; basılı tutma ve hedefte kalma süreleri ayrıca uygulanır.

## Sürüm ve izleme

Uygulama adının yanındaki `v2.1.x` rozeti kurulu sürümü gösterir. `ⓘ` düğmesi
bu sürümün ve önceki sürümlerin güncelleme notlarını açar. Yayın paketinin sürümü
GitHub Actions çalışma numarasıyla otomatik artar. Yeni değişikliklerde
`release_notes.py` içindeki CURRENT_NOTES güncellenip önceki notlar HISTORY'ye alınır.

Yeni bağımsız veya gruba eklenen tuşlarda rastgele gecikme `0.010` saniyedir.
İzlemede `Piksel Seç` sonrası oyun içindeki noktaya sol tıklayın. Tıklamanın
8 fiziksel piksel solu ve 8 fiziksel piksel üstü örneklenir; ESC iptal eder.
Kaydedilen koordinat referans alınır; izleme sırasında ikinci bir kaydırma yapılmaz.
Her RGB kanalında 8 değer tolerans kullanılır. Bu sınır aşılırsa tuş tekrarlanır;
renk tolerans içine döndüğünde bekleyen basış
iptal edilir. Basıştan hemen önce de kontrol yapılır. Okunamayan piksel tetiklemez.
İzleme işaretçisi sürüklenirse yeni renk sürükleme bittiğinde alınır.

## Çalışırken ayar kilidi

Ana sistem aktifken tuşlar, zamanlama, rastgele gecikme, piksel/konum seçimi,
izleme ve Aktif kutuları, grup düzenleme ve profil işlemleri kilitlenir.
Durdurma ve güncelleme notlarını görüntüleme açık kalır. Sistem durdurulduğunda
önceki düzenleme izinleri geri gelir. Grup/zincir aktivasyonu yalnızca geçici
çalışma durumunu değiştirir; kayıtlı tuş ayarlarına ve profillere yazılmaz.

## Tam ekran oyunda izleme tanısı

1. Makroyu durdurup `Piksel Seç`e basın.
2. KAROS'u öne getirin ve oyun çözünürlüğünün yerleşmesini bekleyin.
3. İzlenecek bölgeye sol tıklayın. Örneklenen piksel tıklamanın 8 piksel solu ve
   üstüdür. Belirli bir pikseli seçmek için imleci onun 8 piksel sağına ve altına
   getirin. Seçim penceresi veya F8 kısayolu kullanılmaz.
4. Makroyu başlatın. Kayıtlardaki `İzleme` satırı referans RGB, okunan RGB,
   fiziksel koordinat, ekran alanı, ön pencere ve DPI değerlerini gösterir.
   Aynı tuşa ait farklı kartlar kısa kimlikleriyle ayırt edilir. `izleme kapalı`
   satırı, o kartın normal zamanlayıcı olduğunu belirtir.

Seçimden sonra çözünürlük/monitör düzeni değişirse bu izleme duraklatılır;
oyun içindeyken tıklayarak yeniden seçim yapılmalıdır. Eski profillerdeki referansı
bu yöntemle yeniden seçin. Okuyucu her seferinde güncel ekran bağlamını alır.

Tam ekran DirectX görüntüsünün standart Windows GDI ile yakalanması oyuna ve
ekran moduna bağlıdır; KAROS üzerinde doğrulanmamıştır. RGB değerleri oyun
karesini yansıtmıyorsa pencereli/kenarlıksız modda tekrar test edin. Siyah bir
piksel tek başına hata sayılmaz. Animasyon, imleç/hover, ışıklandırma ve gamma
aynı görünen bölgede RGB değişimine yol açabilir. Kanal başına 8 tolerans, küçük
dalgalanmaları aynı renk sayar; tanı kaydında kullanılan tolerans da gösterilir.

Kayıtlar normal metin gibi fareyle sürüklenip seçilebilir ve Ctrl+C ile kopyalanır.
Seçilen metin değişmesin diye görünür kayıt akışı seçim sırasında bekletilir;
seçim temizlenince devam eder. Dosya günlüğü bu sırada kayda devam eder.
