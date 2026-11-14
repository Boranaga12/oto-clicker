"""Curated notes bundled with the matching application release."""

CURRENT_NOTES = (
    'Grup tuşları tutamaçtan sürüklenerek veya ↑ / ↓ ile sıralanabilir.',
    'Yazı açıyor / Yazı / Yazı kapatıyor bölümleri eklendi; bir grupta birden fazla bölüm kullanılabilir.',
    'Yazı boyunca diğer gruplar, bağımsız tuşlar ve fare makroları duraklar; kalan süreyle devam eder.',
    'Tamamlanan yazı bölümü açılış tutamacından tek parça taşınır; içerideki Yazı seçimleri kilitlidir.',
    'Eksik bölüm başlatılmaz; izleme değişikliği, gönderim hatası veya odak kaybında makrolar durur.',
    'Yazı sırasında zincir eylemler kapanış sonrasına ertelenir; profilin Aktif ayarları korunur.',
)

HISTORY = (
    ("2.1.9", (
        'İzleme ve tıklama işaretçileri makro çalışırken de görünür; tıklamayı geçirir ve odağı almaz.',
        'Seçim beklerken tek nokta önizlemesi, noktanın rengi ve karttaki renk kutusu canlı güncellenir.',
        'Önizleme kayıtlı referansı değiştirmez; izleme ve tıklama hedefleri ayrı korunur.',
        'Alt grup ekleme kaldırıldı; eski alt grupların tuşları sırayla ana gruba aktarılır.',
        'Gruplar aktif tuşları tek tek çalıştırıp tekrar eder; normal tekrar döngüleriyle çakışmaz.',
        'Geçiş süresi alanı kaldırıldı; aralık + rastgele gecikme kullanılır ve basma süresi ayrıca eklenmez.',
    )),
    ("2.1.8", (
        'Piksel seçimi sol tıklamayla yapılır; F8 seçimi kaldırıldı.',
        'İmlecin gri rengi örneklenmesin diye tıklamanın 8 piksel solu ve 8 piksel üstü okunur.',
        'Referans ve çalışma sırasındaki okuma aynı kaydedilmiş koordinatı kullanır.',
        'Önceden imleçten alınan referansları temizlemek için pikseli yeniden seçin.',
    )),
    ("2.1.7", (
        'Kayıtlar fareyle sürüklenerek seçilebilir ve Ctrl+C ile kopyalanabilir.',
        'Seçim sırasında kayıt görünümü sabit kalır; seçim kalkınca bekleyen kayıtlar gösterilir.',
        'RGB karşılaştırmasına kanal başına 8 tolerans eklendi; küçük oyun renk dalgalanmaları tetiklemiyor.',
        'Basış öncesi renk kontrolü de aynı toleransı kullanıyor; renk geri geldiğinde basış iptal ediliyor.',
    )),
    ("2.1.6", (
        'Tam ekran seçimi: Piksel Seç sonrası oyun içinde F8 ile referans alınır; ESC iptal eder.',
        'Fiziksel imleç koordinatları ve erken DPI ayarı kullanılıyor; ekran okuyucu her okumada yenileniyor.',
        'Çözünürlük değiştiğinde izleme duraklar; yanlış noktadan tetikleme yapılmaz.',
        'Tanı kayıtları referans/okunan RGB, pencere, DPI ve hangi kartın bastığını gösteriyor.',
        "Bu sürüm tam ekran sorunlarını ayırt etmek içindir; KAROS'ta doğrulanmış bir çözüm iddiası yoktur.",
    )),
    ("2.1.5", (
        'Makro çalışırken tuş, süre, rastgelelik, izleme ve profil düzenleme kilitleniyor.',
        'Durdurulduğunda ayarlar yeniden düzenlenebiliyor; Durdur düğmesi hep erişilebilir.',
        'Grup ve zincirlerin geçici çalışma durumu kayıtlı Aktif ayarını değiştirmiyor.',
        'Başlatma sırasında açık tuş/piksel seçimleri iptal ediliyor; geç gelen seçimler yok sayılıyor.',
    )),
    ("2.1.4", (
        'Yeni tuşlarda rastgele gecikme varsayılanı 0.010 saniye oldu.',
        'İzlenecek noktanın rengi tek tıklamayla, seçim anında kaydediliyor.',
        'Renk farklıyken tuş belirtilen aralıkla tekrarlanıyor; eşleşince duruyor.',
        'Her basıştan önce piksel yeniden kontrol ediliyor; küçük RGB farkları da algılanıyor.',
        'Sürüm rozeti ve güncelleme notları penceresi eklendi.',
    )),
    ("2.1.3", (
        'Sol klik aralığı en az 0.050 saniye; düşük değerler sessizce düzeltiliyor.',
    )),
    ("2.1.2", (
        'Uygulama paketi yalnızca baslat.bat ve kodlar klasörünü içeriyor.',
        'Sanal ortam kodlar klasörüne alındı.',
    )),
    ("2.1.1", (
        'Otomatik sürüm kontrolü ve güncelleme eklendi.',
        'Profil işlemleri ⋯ menüsüne taşındı; grup başlatma düğmeleri kaldırıldı.',
    )),
)
