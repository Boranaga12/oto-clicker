# İyileştirme ve Profesyonelleştirme Planı

## Tamamlanan — temel güvenilirlik

- Proje modülleri ve mevcut test paketi denetlendi.
- Bağımlılıklar global Python yerine projeye özel `.venv` içine alındı.
- Başlatıcı, gereksinimler değişmedikçe tekrar kurulum yapmayacak hale getirildi.
- Profiller, ayarlar ve loglar yazılabilir kullanıcı veri klasörüne taşındı.
- Eski kullanıcı verileri için tek seferlik, geriye uyumlu geçiş eklendi.
- Profil kaydına son sağlam kopya yedeği ve bozuk dosya karantinası eklendi.
- `NaN`/sonsuz zamanlama değerlerinin worker döngülerini bozması engellendi.
- Sentetik orta tık veya kısayol olaylarının motoru yanlışlıkla açıp kapatması giderildi.
- Tekrarlanan worker hataları ve zincir logları hız sınırlamasına alındı.
- Kritik yeni davranışlar otomatik testlerle güvence altına alındı.

## Sonraki sürüm — ürünleşme

- Eylem zinciri modelini ayrı bir servis ve bağımsız test paketi haline getirmek.
- Çoklu monitörlerde negatif koordinatları ve sanal masaüstü sınırlarını desteklemek.
- Erişilebilir klavye dolaşımı, araç ipuçları ve ölçeklenebilir arayüz eklemek.
- İmzalı tek dosya Windows paketi ve otomatik sürümleme hattı hazırlamak.
- Uzun süreli çalışma, yüksek tıklama hızı ve kapanış yarışları için stres testleri eklemek.

## Dağıtım öncesi kontrol listesi

- Tüm birim testlerini çalıştır.
- Temiz bir Windows kullanıcı hesabında ilk açılışı doğrula.
- Global kısayol, orta tık, piksel izleme ve sabit hedef senaryolarını elle test et.
- `app.log` içinde beklenmeyen hata olmadığını kontrol et.
- Sürüm numarası, değişiklik notları ve kurulum dosyası özetini yayınla.
