# Grup çalışma kuralları

Her grup kendi içinde sırayla döner. Bir turda her etkin kart en fazla bir kez
basılıp bırakılır. Ayrı gruplar bağımsızdır; fiziksel tuş ve fare girişleri
ortak kilitle sıraya alınır.

## Kartlar arasındaki bekleme

Grup içindeki kartların üzerinde aralık ve rastgelelik girişi bulunmaz. Kartın
altındaki bağlantı, o kart bırakıldıktan sonraki beklemeyi gösterir:

`Bekleme + 0 ile rastgele ek sürenin arasında seçilen değer`

Örnek: `1,0 sn + rastgele 0…0,2 sn`, sonraki adımdan önce 1,0–1,2 saniye
bekletir. Son kartın bağlantısı başa dönmeden önceki beklemedir. Sıfır bekleme
geçerlidir; fiziksel tuşun basılı kalma ve bırakılma süreleri yine tamamlanır.
Bekleme her başarılı adım için bir kez seçilir; birikmiş basış kuyruğu yoktur.

Eski profillerdeki aralık ve rastgelelik sayıları ilk yüklemede bu geçişlere
aktarılır. Yeni bekleme, eski başlangıçtan başlangıca aralık yerine tuş
bırakıldıktan sonra başlar. Bağımsız kartların aralıkları etkilenmez.

| Durum | Grup davranışı |
| --- | --- |
| Etkin, izlemesiz kart | Bir basış; ardından kendi geçiş beklemesi |
| Etkin, izleme koşulu uygun kart | Bir basış; sonraki turda koşul yeniden değerlendirilir |
| Pasif kart veya uygun olmayan izleme koşulu | Atlanır; kendi geçiş beklemesi uygulanmaz |
| Bütün adımlar atlanıyor | 50 ms sonra yeniden bakılır; işlemciyi tüketen boş döngü oluşmaz |
| Geçiş sırasında koşul değişiyor | Sırası geldiğinde güncel koşul kullanılır |
| Tıklama için fare taşınınca hover rengi değişiyor | Önceden onaylanan tek grup tıklaması iptal edilmez |
| Durdur/iptal | Bekleme kesilir; yeni basış gönderilmez; tutulan giriş bırakılır |
| Girdi gönderme hatası | Bu grup durur ve hata kayda yazılır; sonraki karta sessizce geçilmez |
| Yazı bölümü | Açılış–gövde–kapanış birlikte korunur; bölüm içi geçişler uygulanır |
| Yazı kapanışının beklemesi | Yazı kilidi bırakıldıktan sonra uygulanır |
| Başka yazı veya doğrulanmış merkeze dönüş | Normal adımların beklemesi duraklar; sonra kalan süre devam eder |
| Koordinat okunamıyor | Yalnızca yürüyüş duraklar; normal gruplar devam eder |
| Grup içi Tab yenileme süresi dolmuş | Tab ancak kendi sırası geldiğinde bir kez basılır |

Tıklama başarısız görünse bile kör bir ikinci tıklama gönderilmez. Böylece
tek tıklamanın satın alma, seçim değiştirme veya başka bir eylemi iki kez
tetiklemesi önlenir. Grup fare adımlarında oyunların girdi örneklemesi için
daha uzun basma ve bırakma aralıkları kullanılır.
