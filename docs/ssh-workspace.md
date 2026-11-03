# Kullanıcı çalışma alanı ve SSH

NETRIX'in envanter tablosundaki sol terminal butonu, seçilen cihaza kullanıcının kendi SSH bilgileriyle bağlantı açar. Cihaz kimliği mevcut merkezi envanterden gelir; IPAM veya komşuluk yazılmaz. Ağ işlemlerini aynı container'daki `netrix-ssh` worker süreci yürütür. API ağ cihazına bağlanmaz.

## Kullanım ve yetki

1. **Profil → Cihaz yetkisi → SSH Bağlantısı** altında kullanıcı adı, şifre veya özel anahtar, port, isteğe bağlı anahtar parolası, ilk komut ve bağlantı zaman aşımı kaydedilir. Şifre alanını boş bırakmak mevcut şifreyi korur; **Kayıtlı bağlantıyı kaldır** bütün kişisel bağlantı bilgisini temizler. Sırlar API'den geri okunmaz.
2. **Profil → Cihaz yetkisi → Cihaz grupları** kişisel cihaz listelerini tutar. Envanterdeki tüm güvenli alanlar (model, üretici, versiyon, tür, lokasyon, VRF vb.) aynı koşul sistemiyle filtrelenir. Alan değerleri mevcut kayıtlardan önerilir. Sayfadaki cihazlar veya filtreye uyanların tamamı topluca seçilebilir. Arama, filtre ve sayfa değişince seçimler korunur. Gruplar kullanıcı veya SSH yetkisi içermez; yöneticiler dahil yalnız sahibi tarafından görülür ve düzenlenir.
3. Yönetici **Ekip & yetkiler** ekranında **Kullanıcı rollerini düzenle** ile bağımsız **SSH bağlantısı** rolünü atar veya kaldırır. Bu rol izleyici/operatör uygulama rolüne eklenebilir; envanterdeki uygun cihazlarda kişisel SSH bağlantısı ve toplu komut yetkisi verir. Yöneticiler bu yetkiyi zaten taşır. Rolü olmayan kullanıcı kendi cihaz gruplarını düzenleyebilir, SSH oturumu başlatamaz. Kullanıcı kendisine rol atayamaz; rol değişikliği yalnız yönetici API'sinden yapılır.
4. Yalnız envantere ait, arşivlenmemiş, aktif veya bakım durumundaki cihazlara bağlantı açılır. Bağlantı mevcut keşif kapsamının etkinliğine veya tarama zamanlamasına bağlı değildir. Kullanıcıdan serbest hedef IP alınmaz.
5. Cihazın mevcut `ssh_trust_host_key` tercihi uygulanır. Kapalı varsayılanda `known_hosts` doğrulaması zorunludur. Kişisel profil bu politikayı devre dışı bırakamaz.

Terminal penceresinde hazır komut kitaplığı, tam ekran, küçültme ve yeni sekmeye aktarım vardır. Yeni sekme aynı SSH oturumunu alır; yeni cihaz bağlantısı veya ilk komut tekrarı oluşturmaz. Aynı oturumun önceki görüntüleyicisi devre dışı kalır. Başka hesap oturum kimliğini bilse de erişemez. Yeni sekme site oturum cookie'sini kullanır; parola veya token URL'ye konmaz.

Alt şerit en fazla 15 küçültülmüş oturum tutar. Kullanıcı başına 16, uygulama genelinde 32 açık SSH oturumu vardır. Sekmeler de aynı sunucu sınırına tabidir. Terminal 15 dakika kullanıcı girdisi olmadığında, 4 saat sonunda veya 60 saniye görüntüleyici bulunmadığında kapanır. Sayfalar arasında gezinmek ve küçültmek bağlantıyı korur. Tarayıcı yenilemesi kalıcı oturum geri yükleme sağlamaz. Çıkış, kullanıcı pasifleştirme ve cihaz uygunluğunun veya SSH rolünün kaldırılması en geç 10 saniyelik denetimle bağlantıyı sonlandırır; kullanıcı girdisinde en fazla iki saniyelik ek yetki önbelleği kullanılır.

## Toplu komut

Envanterde cihazlar seçilip **Toplu komut gönder** açılır. En fazla 100 hedefin tamamı kabul sırasında yetkilendirilir; tek bir yetkisiz hedef bütün kabulü reddeder. Her hedef worker'da bağlantı öncesinde yeniden doğrulanır. Kullanıcı başına bir, uygulama genelinde dört etkin toplu istek kabul edilir; worker aynı anda en fazla iki istek ve istek başına dört cihaz bağlantısı çalıştırır. Yeni terminal bağlantıları toplu iş kuyruğundan bağımsız kabul edilir.

Başarılı, başarısız, çalışan, bekleyen ve iptal edilen cihazlar ayrı listelenir; seçilen cihazın çıktısı karşısında gösterilir. Linux exec kanalı gerçek çıkış kodunu kullanır. Ağ CLI'ı PTY açar; tanınan komut hatası başarısızdır. Prompt dönmeyen interaktif/parolalı komutlar, sayfalı veya uzun çıktılar süre/boyut sınırında başarısız olabilir; bunlar etkileşimli terminalde yürütülmelidir. Başarı CLI komutunun yanıt verdiğini belirtir; cihazın işlevsel sonucunu veya yeniden başlatma sonrası durumunu doğrulamaz.

Cihaz başına süre 5–120 saniye (varsayılan 30), çıktı 64 KiB ve toplu sonuç toplamı 2 MiB ile sınırlandırılır. Sonraki çıktılar toplam sınırda işaretlenerek kısaltılır. İptal ve pencereyi kapatma kalan gönderimleri durdurur; cihaza ulaşmış bir komutu geri alamaz. Çalışan istekte erişim beş saniyede bir yeniden denetlenir.

Komutlar ve başlangıç komutu otomatik yeniden denenmez. Redis teslimi bir kez sahiplenilir; aynı teslim veya worker yeniden başlaması komutu tekrar çalıştırmaz. Kesilen işlem açık başarısız/iptal durumuna geçer. Zaman aşımı sonrasında cihazda gerçekten ne uygulandığı terminalden doğrulanmalıdır.

## Veri ve kaynak kullanımı

MariaDB'de kullanıcı başına tek `user_workspaces` kaydı tutulur: küçük tercih JSON'u, Fernet ile şifreli SSH bilgileri ve en fazla 50 hazır komut. Grup tanımı ve cihaz üyelikleri indeksli ilişkilerdir. Grup en fazla 10.000 cihaz içerir. Tümünü seç işlemi yalnız kimlikleri sorgular; sonuçlar ve aramalar veritabanına yazılmaz. SSH rolü kullanıcı kaydında tek boolean alandır; eski grup-kullanıcı yetki tablosu kaldırılmıştır. Bağlantı/komut istekleri yalnız metadata audit kaydı oluşturur; komut metni, şifre, terminal çıktısı ve tuş vuruşları audit'e veya kalıcı iş tablosuna yazılmaz.

Redis'teki terminal giriş/çıkış ve toplu komut/sonuç içeriği uygulama anahtarıyla şifrelenir. Giriş akışı 128 mesajla sınırlandırılır ve işlenen mesajlar silinir. Çıkış en fazla 128 adet 4 KiB metin parçasıdır; tarayıcı scrollback'i 1000 satırdır. Etkin kayıtlar en fazla dört saat, kapanan terminal ve toplu sonuçlar 10 dakika tutulur. Redis AOF fiziksel yeniden yazımına kadar şifreli eski blokları içerebilir; kalıcı terminal arşivi oluşturulmaz.

Terminal WebSocket'i aynı Origin, mevcut HttpOnly oturum cookie'si, oturum sahibi ve bağlı cihaz yetkisini denetler. Mesaj boyutu ve saniyelik giriş sınırı uygulanır. SSH host anahtarı/şifre hataları sabit ve sır içermeyen mesajlara çevrilir. Terminal metni HTML olarak yorumlanmaz. xterm.js yalnız ilk terminal açıldığında, uygulamanın kendi yerel asset'inden yüklenir. Worker boşta bloklayan Redis okuması kullanır; heartbeat üç saniyede bir yazılır.

## Profil

Sol alttaki kullanıcı adının altındaki **Profil** menüsü hesap bilgileri, altı kurumsal palet, tarih/saat/bölge ve özellikler ile Cihaz yetkisi alt menüsünü içerir. Teknik kobalt, Atlantik, Ametist, Bakır, Orman ve Grafit paletlerinin açık/koyu değerleri ayrıdır. Saat dilimi geçerli IANA adıdır; UTC saklama değişmez, gösterim `Intl.DateTimeFormat` ile kullanıcı tercihine göre yapılır. Hazır komutlar, oturum şeridi, sıkı envanter tabloları ve azaltılmış hareket kişisel tercihlerdir; erişim yetkisi sağlamaz. Tercihler başka kullanıcıya taşınmaz.

## Şema ve doğrulama

Alembic `20261103_34` çalışma alanı tablolarını ekler. `20261103_36`, eski etkin gruplarda yönetici tarafından açıkça yetkilendirilmiş kullanıcılara SSH rolünü aktarır, grup yetki sütununu ve grup-kullanıcı tablosunu kaldırır; cihaz üyelikleri, sahiplik ve şifreli bilgiler korunur. Önceki cihaz bazlı kapsam yeni bağımsız rol ile envanter kapsamına genişler. Atanmış SSH rolleri varken revision 35’e downgrade reddedilir. Kayıtlı çalışma alanı veya grup varken downgrade veri kaybına karşı reddedilir. Önce kayıtlar açıkça kaldırılmalıdır.

- `tests/test_user_access.py`: şifreleme, sır yansıtmama, kullanıcı izolasyonu, yetki yükseltme reddi, envanter sınırı, kapasite, iptal ve çıktı sınırı.
- `scripts/ssh_workspace_check.py`: yalnız loopback sahte SSH sunucusu ve boş test Redis ile gerçek SSH/WebSocket; host anahtarı, yanlış parola, ilk komut, terminal girdisi, sekme devri, toplu başarı/hata/süre aşımı ve teslim tekilliği.
- `scripts/user_workspace_browser_check.py`: gerçek yerel HTTP API, açık terminal WebSocket mock'u; masaüstü/mobil, açık/koyu, altı palet, hizalar ve axe. Gerçek cihaz SSH testi değildir.
- `scripts/user_access_mariadb_check.py`: yalnız atılabilir MariaDB `netrix_test` üzerinde eski verinin korunması, yeni tabloların şema eşitliği, UTC, FK/UNIQUE, eşzamanlı grup ve korumalı downgrade/upgrade. Önceki revision 33'ün DESC journal indekslerinin MariaDB reflection farkı bu yeni tabloların eşitlik kontrolünün dışındadır.
