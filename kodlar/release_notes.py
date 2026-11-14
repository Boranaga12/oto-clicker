"""Curated notes bundled with the matching application release."""

CURRENT_NOTES = (
    "Makro çalışırken tuş, süre, rastgelelik, izleme ve profil düzenleme kilitleniyor.",
    "Durdurulduğunda ayarlar yeniden düzenlenebiliyor; Durdur düğmesi hep erişilebilir.",
    "Grup ve zincirlerin geçici çalışma durumu kayıtlı Aktif ayarını değiştirmiyor.",
    "Başlatma sırasında açık tuş/piksel seçimleri iptal ediliyor; geç gelen seçimler yok sayılıyor.",
)

HISTORY = (
    ("2.1.4", (
    "Yeni tuşlarda rastgele gecikme varsayılanı 0.010 saniye oldu.",
    "İzlenecek noktanın rengi tek tıklamayla, seçim anında kaydediliyor.",
    "Renk farklıyken tuş belirtilen aralıkla tekrarlanıyor; eşleşince duruyor.",
    "Her basıştan önce piksel yeniden kontrol ediliyor; küçük RGB farkları da algılanıyor.",
    "Sürüm rozeti ve güncelleme notları penceresi eklendi.",
)),
    ("2.1.3", (
        "Sol klik aralığı en az 0.050 saniye; düşük değerler sessizce düzeltiliyor.",
    )),
    ("2.1.2", (
        "Uygulama paketi yalnızca baslat.bat ve kodlar klasörünü içeriyor.",
        "Sanal ortam kodlar klasörüne alındı.",
    )),
    ("2.1.1", (
        "Otomatik sürüm kontrolü ve güncelleme eklendi.",
        "Profil işlemleri ⋯ menüsüne taşındı; grup başlatma düğmeleri kaldırıldı.",
    )),
)
