# Yerel giriş ve Authenticator

Yerel hesaplarda parola doğrulaması tek başına oturum açmaz. İlk girişte Microsoft Authenticator, Google Authenticator veya uyumlu bir TOTP uygulamasıyla QR kodu taranır; manuel anahtar da aynı kurulum ekranındadır. NETRIX yalnız doğru altı haneli kod alındığında kurulumu etkinleştirir ve oturum çerezi verir. Sonraki girişler yalnız kod ister. Microsoft Entra ID girişinin doğrulama politikası kimlik sağlayıcısında kalır.

TOTP, RFC 6238 SHA-1 / 30 saniye / 6 hane kullanır; bir önceki ve sonraki zaman dilimi kabul edilir. Kullanılan zaman dilimi tekrar kabul edilmez. Beş dakikalık, tek kullanımlık istekler SQL'de yalnız SHA-256 özetiyle tutulur; yeni parola girişi önceki isteği geçersiz kılar. Beş hatalı kod isteği kapatır; IP başına mevcut Redis hız sınırı ayrıca uygulanır. Redis erişilemiyorsa giriş kapalı kalır.

Kurulum sırları uygulamanın mevcut ortam/secret şifreleme anahtarıyla şifrelenir. Sırlar yalnız parola kanıtı sonrası ilk kurulum yanıtında görünür; kullanıcı listesi, ayrıntı, denetim ve oturum yanıtları sır içermez. API yanıtları önbelleğe alınmaz. QR üretimi yereldir, üçüncü tarafa sır gönderilmez. İlgili sütunlar `yonetim.users` sahibindedir; yeni envanter veya hesap tablosu oluşturulmaz.

Süper yönetici **Kullanıcı rollerini düzenle → Authenticator MFA → MFA’yı sıfırla** üzerinden onayla sıfırlar. Bu işlem tüm hedef oturumlarını ve bekleyen doğrulama isteğini iptal eder. Sonraki yerel girişte yeniden kurulum zorunludur; MFA'yı kapatma seçeneği yoktur. Telefonunu kaybeden kullanıcı başka bir süper yöneticiye başvurur. Tek süper yöneticinin erişim kaybında yetkili işletmen korumalı SQL erişimiyle ilgili hesabın MFA alanlarını ve oturumlarını sıfırlamalıdır; parola girişi zorunlu kalır.

Migration `20261122_06`, MFA öncesi yerel oturumları kapatır. Kullanıcılar dağıtım sonrası yeniden giriş yaparak Authenticator kurar. SAML oturumları korunur.

Doğrulama: `pytest tests/test_local_mfa.py` RFC test vektörlerini, oturumsuz parola adımını, şifrelemeyi, tekrar kullanımını, deneme/süre sınırını ve sıfırlama yetkisini denetler. Mevcut yetki testleri `tests/auth_helpers.py` ile iki adımı tamamlar; gerçek ağa erişilmez.

Tarayıcı: ayrı terminalde `PYTHONPATH=backend python scripts/local_mfa_fixture.py`, ardından `python scripts/local_mfa_browser_check.py`. Fixture geçici SQLite ve sahte Redis kullanır; gerçek entegrasyon, cihaz veya zamanlayıcı başlatmaz. 1440px, 375px ve yatay mobilde iki tema, QR sınırları, hata/başarılı doğrulama, Microsoft/yerel görünümü ve kullanıcı MFA paneli kontrol edilir. `artifacts/local-mfa` ekranları yalnız geçici test hesabına aittir.

Protokol başvurusu: [RFC 6238](https://www.rfc-editor.org/rfc/rfc6238). QR kütüphanesi: [qrcode 8.2](https://pypi.org/project/qrcode/8.2/).
