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
- Otomatik zamanlamalı, düz ve sıralı çalışma grupları
- Atomik profil ve ayar kaydı
- Kurulum klasöründen bağımsız `%APPDATA%\ArikMakro` profil saklama
- Önceki LocalAppData ve taşınabilir sürümlerden otomatik profil göçü
- Dönen `app.log` hata kayıtları

## Karos konum kontrolü

Her profilin en üstündeki karttan **Konumu Seç** ile yalnızca `67.6 77.5`
gibi iki koordinatı veya sabit zemindeki `71.9 / 57.2` satırını çevreleyen dar
bir alan çizin; alttaki ikonları dahil etmeyin. Her iki gösterge aynı kartla okunur.
Esc önceki seçimi korur. Çerçeve tıklamayı engellemez ve seçimi kaldırana kadar
görünür kalır. Ekran düzeni değişirse alanı yeniden seçin.

Karakter dururken **Anlık Konumu Al** ile üç tutarlı okumadan merkez kaydedin.
`0 ≤ Min < Maks` olacak şekilde mesafeleri ayarlayıp kartı etkinleştirin.
İki güvenilir okumada Maks aşılırsa normal makrolar durur; W sürekli basılı
tutulurken A/D ile yön düzeltilerek Min mesafesine dönülür. Kısa OCR hataları
bu iki ölçümün doğrulamasını sıfırlamaz. İlerleme durursa önce bir yana dönülür,
biraz ilerlenir, sonra yeniden merkez hedeflenir; sonraki denemede diğer yan
denenir. Bu, koordinat geri bildirimli kaçınmadır; haritadan rota çıkarmaz.
Bir dönüş en fazla 90 saniye etkin yürüyüş ve sekiz kaçınma dener; aşılamayan
engelde normal makrolar bekletilir ve durum kartta açıklanır.

Yazı bölümleri yürüyüşten önceliklidir; yazı bitince yeni konum doğrulanır.
Yazı dışındaki W/A/S/D kartları geçici olarak bastırılır; kayıtlı aktiflikleri
değişmez. Konum ayarları çalışma sırasında düzenlenemez.

Okuma, tek bir gizli Windows PowerShell sürecindeki yerel Windows OCR motoruyla
yapılır. Ek Python paketi veya bulut servisi kullanılmaz. Windows OCR dili yoksa
kart açıklamayla pasif kalır; Windows dil ayarlarından OCR destekli bir dil
kurulmalıdır. Görüntüler diske veya ağa gönderilmez.

Aktif kutusu sistem duruyorken her zaman açılıp kapatılabilir; eksik ayarlar
bu tercihi sıfırlamaz. Kartın durum satırı eksik alanı, merkezi veya OCR sorununu
açıklar. Eksik gereksinimde konum denetimi bekler; normal makrolar başlayabilir. OCR sorunu varsa
karttaki ayrıntıyı kontrol edin; **Windows Dil Ayarları** ile OCR destekli bir
dilin Metin Tanıma bileşenini yükleyip **OCR’yi Yeniden Dene** düğmesini kullanın.
İngilizce ABD yoksa bilgisayarda yüklü diğer OCR dilleri otomatik denenir.
Yavaş bilgisayarlarda merkez için 45 saniyeye kadar beklenir; doğrulanan okuma
sayısı kartta 0/3 olarak gösterilir. Kısa okuma araları tutarlı ölçümleri silmez.

Koordinat okunamazsa yalnızca otomatik yürüyüş bırakılır; normal tuşlar ve
gruplar çalışmaya devam eder. Okuma düzelince konum tekrar değerlendirilir;
devam eden merkeze dönüş gerekiyorsa otomatik sürer. Eksik konum verisi tek
başına normal bekleme sayaçlarını durdurmaz. Yazı, odak kaybı ve durdurma
yürüyüş tuşlarını bırakır. Alanı kaldırmak Aktif tercihini değiştirmez.

Aç/kapa kısayoluna atanmış makro gönderildiğinde sistem kendini durdurur. Bu
kartın izlemesi seçilen renk **bulununca** çalışır. Diğer kartlar renk farklıyken
çalışmaya devam eder. İzlemesi açık Tab, dört etkin saniye basılmadığında bir
yedek basış yapar. Bu süre yalnızca Tab kartlarında görünen **Tab yenilenme (sn)**
alanından değiştirilebilir; varsayılan 4 saniyedir. Yazı bölümlerinin içindeki
Tab bundan muaftır. Yazı ve
yürüyüşte geçen süre bu dört saniyeye eklenmez.
Grup içindeki Tab yenilemesi kendi sırası geldiğinde uygulanır; başka kartın
arasına fazladan Tab gönderilmez.

## Sıralı grupların kullanımı

1. `+ Grup` ile bir ana grup oluşturun.
2. Grubun `+ Tuş` düğmesiyle adımları ekleyin. Gruba grup eklenmez.
3. Çalışacak tuşların `Aktif` kutusunu açın. Kartlar arasından bekleme ve rastgele ek süreyi ayarlayın.
4. Ana `BAŞLAT` tüm grupları başlatır. Her grup kendi içinde sırayla döner.

Bir grupta bir anda yalnızca bir adım yürütülür. Tuş bir kez basılıp bırakılır;
sonra kartın altındaki `bekleme + 0…rastgele ek süre` uygulanır. Son kartın
beklemesi başa dönmeden öncedir. Atlanan kartın kendi beklemesi uygulanmaz.
İzleme uygun kaldığında kart sonraki turda yeniden basılabilir; bağımsız tekrar
iş parçacığı veya bekleyen basış kuyruğu oluşturmaz. Grup tıklamasında fare
üzerine gelince renk değişmesi, önceden onaylanan basışı iptal etmez. Durdurma
beklemeyi keser; giriş hatasında grup sonraki karta sessizce ilerlemez.

Eski aralık ve rastgelelik sayıları geçişlere bir kez aktarılır; artık tuş
bırakıldıktan sonraki bekleme anlamına gelir. Bağımsız kartlar değişmez.

Eski iç içe grupların tuşları ana grubun içine, aynı sıra korunarak taşınır.
Aynı kayıtlı tuş birden fazla grupta yer alıyorsa ilk gruptaki üyelik kullanılır.
Kayıtlı Aktif ayarları başlatma/durdurma sırasında değiştirilmez.

## Mimari

- `main.py`: uygulama yaşam döngüsü ve hata kaydı
- `gui.py`: Tkinter arayüzü
- `ui_widgets.py`: tema ve tekrar kullanılabilir arayüz bileşenleri
- `engine.py`: global giriş dinleyicileri ve worker yönetimi
- `workers.py`: klavye, fare ve piksel izleme worker'ları
- `sequences.py`: düz grup modeli, eski alt grupları dönüştürme ve profil serileştirme
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
Seçili izleme noktaları pembe, tıklama noktaları mavi küçük işaretçilerle gösterilir.
Noktayı değiştirmek için seçim düğmesini yeniden kullanın.

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

## Noktalar ve canlı önizleme

Seçili izleme ve sabit tıklama noktaları sistem çalışırken de görünür kalır.
Windows işaretçileri tıklamayı geçirir ve odağı almaz; merkezleri saydamdır.
Örneklenen diğer noktaların üstüne gelen işaretçi kısımları da saydam bırakılır.

`Piksel Seç` veya `Konum Seç` beklerken küçük bir nokta imleci takip eder.
İzlemede bu nokta imlecin 8 piksel solu ve üstü, tıklama hedefinde tam imleç
konumudur. Noktanın rengi ve tuş kartındaki renk kutusu o piksele göre canlı
olarak güncellenir. Tıklamadan önce kayıtlı referans veya profil değiştirilmez.
ESC ile iptal edilince referans renk kutusuna geri gelir. İzleme seçimi sadece
izleme referansını, konum seçimi sadece fare hedefini değiştirir.

Özel tam ekran oyunların harici Windows işaretçilerini gösterme davranışı oyuna
bağlıdır; KAROS üzerinde görünürlük bu ortamda doğrulanmamıştır.


## Grup sıralaması ve yazı bölümleri

Makro duruyorken grup kartındaki ⠿ tutamacını sürükleyin veya ↑ / ↓ kullanın.
Bırakılacak sıra çizgiyle gösterilir; listenin kenarında otomatik kaydırılır.
Sıralama aynı grup içinde yapılır ve hemen kaydedilir.

Sohbeti açan tuşta **Yazı açıyor**, sonraki kapatan tuşta **Yazı kapatıyor**
seçin. Aradaki kartlar otomatik olarak kilitli **Yazı** olur. Kapanıştan sonra
yeni bir yazı bölümü oluşturabilirsiniz. Açılış tutamacı tamamlanmış bölümü
birlikte taşır; iç tuşlar ayrı sıralanabilir veya dışarı taşınabilir. Kapanış
kartı bölümü geride bırakarak taşınamaz. Açılış seçimini kaldırmak o bölümü
bilerek kaldırır; kapanış seçimini kaldırmak bölümü eksik bırakır.

Yazı boyunca diğer gruplar, bağımsız tuşlar ve otomatik fare basımları duraklar.
Başlamış basım önce bırakılır. Kapanış tuşunun aralığı tamamlandığında kalan
süreler devam eder; kaçırılan basımlar biriktirilmez. Eşzamanlı yazı istekleri
sırayla işlenir. Zincir eylemler kapanış sonrasına ertelenir. Kayıtlı Aktif
seçimleri değişmez. Fiziksel klavye ve fare kullanımınız engellenmez.

Bölümde bir tuş Aktif değilse veya başlangıçtaki izleme koşullarından biri
uygun değilse bütün bölüm o tur atlanır. Her izlemeli basımdan önce piksel
yeniden kontrol edilir. Bölüm sırasında koşul değişirse, okuma/gönderim
başarısız olursa veya hedef pencerenin odağı değişirse bütün makro durur.
Sohbeti kontrol ederek yeniden başlatın; yarıda kalan yazı devam ettirilmez.
Uygulama öndeyse ilk yazı oyun penceresine geçilene kadar bekler.

Açılış/kapanış silinirse bölüm eksik kalır ve makro başlatılmaz. Karttaki
**Yazı eksik · Düzelt** işlemi eksik bölümleri onayla kaldırır; iç tuşlar normal
tuşlara döner. Eski profillerde yazı bölümü bulunmaz; tuşlar aynen korunur.

Gönderilen tuşun oyunda işlenmesi oyuna bağlıdır. Kapanışın gerçekten
sohbeti kapattığını doğrulayan ayrı bir ekran algılayıcısı yoktur; kapanış
tuşu ve süresi oyunda denenmelidir. Hata halinde otomatik Enter/Escape
gönderilmez. KAROS üzerinde gerçek oyun testi bu geliştirme ortamında yapılamaz.


## Grup kilidi ve profil isimleri

Grup isminin solundaki kutu grubun tamamını etkinleştirir. İşaretini kaldırınca
grup çalışmaz, iç kontroller kilitlenir ve çok soluk görünür. Kutuyu tekrar
seçerek açın. İç tuşların Aktif değerleri bu işlemden etkilenmez. Aktif olmayan
tuşlar da soluk görünür; grubunuz açıksa tuşun kendi Aktif kutusu ile açılabilir.
Makro çalışırken bu seçimler de diğer ayarlar gibi değiştirilemez.

Yeni grup ve bağımsız tuşların rastgele süresi 0.100 saniyedir. Var olan tuşların
kayıtlı süreleri değişmez. İzleme kapalıyken renk kutusu gösterilmez.

Profil menüsündeki **⋯ → İsmi değiştir** işlemi Varsayılan dahil her profilde
kullanılır. Tuşlar, gruplar, yazı bölümleri ve profil sırası korunur. Aynı isimle
ikinci bir profil oluşturulamaz. Tümünü sıfırla seçeneği menüden kaldırılmıştır.


## Kart güncellemeleri

Kartlar tuş kimliğiyle eşleştirilir. Bir tuş eklemek yalnızca o kartı oluşturur;
silme yalnızca ilgili kartı kaldırır. Sıralama mevcut pencereleri taşır; yazı
etiketleri, grup kilidi ve ayarlar mevcut kontroller üzerinde güncellenir.
Düzenlenmekte olan alanlar ve seçimler ilgisiz güncellemelerde korunur.

Son üç profilin görünümü ve kaydırma konumu bellekte tutulur. Daha eski
profillerin görünümü bellek kullanımını sınırlamak için bırakılır ve yeniden
seçildiğinde oluşturulur. İlk açılışta ve bir kart başka bir gruba taşındığında
yeni Tk üst öğesine ait kart oluşturulması gerekir.

Süre, renk ve koordinat bilgileri mevcut tuş çalışanlarınca okunur. Yalnızca
döngü biçimi değişen çalışan durdurulup yenilenir; kapanmayan eski çalışanın
üstüne ikinci bir çalışan başlatılmaz. Aynı değerle alandan çıkmak veya mevcut
profili tekrar seçmek diske kayıt ve motor yapılandırması başlatmaz.

Kartlar belirgin yüzeyler ve kenar çizgileriyle ayrılır. Yazı bölümündeki kartlar
mor şerit kullanır. Grup içindeki sürükleme ve ↑ / ↓ kontrolleri sağdaki Sil
düğmesinin hemen üstündedir.
