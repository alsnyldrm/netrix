# Profil görselleri

Profil → Hesabım → Kişisel çalışma alanı, fotoğraf yükleme ve 10 hazır anime avatarından seçim sunar. Seçim hesaba kaydedilir, sol menüde hemen görünür; kaldırma baş harfleri geri getirir. Yeni hesaplara rastgele karakter atanmaz.

Fotoğraf kabul sınırı 5 MB ve 16 megapikseldir; JPG, PNG ve hareketsiz WebP/PNG kabul edilir. Sunucu yön bilgisini uygular, merkezden kare kırpar, 256×256 WebP olarak yeniden kodlar ve metadata'yı kaldırır. Fotoğraf yalnız sahibinin oturumuyla okunur, genel kullanıcı listesine veya audit verisine eklenmez. Ayrı `user_avatars` tablosu kullanıcı tercih güncellemelerinden etkilenmez. Nginx'te yalnız `/api/v1/access/avatar` için 5 MB sınırı tanımlıdır.

Hazır karakterler popüler anime karakterlerinden bir seçkidir; evrensel veya resmi bir dünya sıralaması iddiası taşımaz. Görseller yerleşik `imagegen` aracıyla ayrı ayrı oluşturulmuştur. Üretim istemleri ve kaydedilen dosya yolları [avatar-prompts.json](avatar-prompts.json) içindedir. Görseller `frontend/public/avatars/` altında uygulamayla dağıtılır; üçüncü taraf görsel sunucularına istek yapılmaz.

Doğrulama: `tests/test_profile_avatars.py` hesap izolasyonu, kalıcılık, metadata temizleme, dosya doğrulama, değiştirme ve kaldırma davranışını kapsar. `scripts/profile_avatar_browser_check.py` yerel fixture üzerinde gerçek yükleme, yeniden açma, klavye ve masaüstü/mobil erişilebilirlik kontrolünü yapar. `scripts/profile_avatar_migration_check.py` yalnız `netrix_test` adlı geçici MariaDB'de yeni tablonun şema uyumunu, BLOB/FK/tekillik/kaynak kısıtlarını, kullanıcı silinmesini ve migration geri/ileri geçişini doğrular.
