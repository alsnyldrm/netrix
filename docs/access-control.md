# NETRIX rol ve erişim sözleşmesi

`super_admin` yönetici ve operatör işlemleri ile kişisel SSH dahil uygulamadaki tüm erişimi kapsar. Aktif bir yerel veya Microsoft Entra ID hesabına yalnız başka bir süper yönetici tarafından, **Yönetim → Ekip & yetkiler → Kullanıcı rollerini düzenle** üzerinden verilebilir veya kaldırılabilir. Entra rol eşlemeleri bu rolü veremez; Entra girişleri elle verilen rolü değiştirmez. İlk yerel kurtarma hesabının rolü düşürülemez, e-posta adresi değiştirilemez ve hesap devre dışı bırakılamaz. Yetki verilmiş başka bir hesabı devre dışı bırakmak için önce süper yönetici rolünü kaldırın.

Süper yönetici, **Ekip & yetkiler** ekranında yerel ve Entra hesaplarını tek tek veya seçerek silebilir. Kendi hesabı ve ilk yerel kurtarma hesabı silinemez. Silme işlemi uygulama erişimini ve oturumları kapatır, kişisel ayarları ve SSH profillerini temizler, denetim ve görev geçmişi için kimlik kaydını korur. Silinen Entra kimliği bir sonraki girişte tekrar oluşturulmaz. Aynı e-posta adresiyle yeni bir yerel hesap açılabilir.

Boş kurulumun tek kullanımlık kurulum anahtarı yalnız bu e-posta hesabıyla ilk süper yöneticiyi oluşturur; farklı bir hesapla kurulumu tamamlayıp sistemi rol atayamaz durumda bırakmaz.

| Yetenek | İzleyici | Operatör | Yönetici | Süper yönetici |
| --- | --- | --- | --- | --- |
| Yetkili envanteri görüntüleme | Evet | Evet | Evet | Evet |
| Operatör yazma/konfigürasyon işlemleri | Hayır | Evet | Evet | Evet |
| Yönetici işlemleri, kullanıcı ve denetim listeleri | Hayır | Hayır | Evet | Evet |
| Uygulama rolü / SSH yetkisi atama | Hayır | Hayır | Hayır | Evet |
| Kullanıcıları silme | Hayır | Hayır | Hayır | Evet |
| Kişisel SSH, toplu komut ve kişisel cihaz grupları | Açık SSH atamasıyla | Açık SSH atamasıyla | Açık SSH atamasıyla | Tam erişim |

Sıradan yöneticiler yeni hesabı yalnız izleyici olarak ve SSH yetkisi olmadan açabilir; atama alanları gösterilmez. User creation API'si üzerinden yönetici/operatör/süper yönetici veya SSH yetkisi verme girişimi 403 alır. Rol atama API'si yalnız süper yöneticiye açıktır. Süper yönetici rolü mevcut hesaba rol atama API’si üzerinden verilir. Rol değişiklikleri denetim izine kaydedilir.

Arayüz yetkisiz eylemleri göstermez. SSH yetkisi yoksa envanterde terminal sütunu ve toplu komut, profil altında cihaz yetkisi/SSH/gruplar, özelliklerde hazır komut ve oturum şeridi tercihleri kaldırılır. Yetkisiz terminal ve toplu komut sekmeleri araçları açmaz; kişisel SSH verisi için HTTP isteği göndermez. Yönetici olmayan hesapların kullanıcı/denetim sayfalarına doğrudan hash ile gitmesi genel bakışa döner. İzleyiciye genel bakışta kayıt ekleme sunulmaz. API yetkilendirmesi arayüzden bağımsızdır.

Rol değişikliği canlı yenileme olayı yayımlar. Açık tarayıcı sunucudaki kullanıcı bilgisini yeniden okur; ayrıca görünür sayfadaki mevcut 30 saniyelik yenileme kullanıcı bilgisini de günceller. SSH worker'ı başlangıçta ve en geç 10 saniyede bir kullanıcı/rol/grup yetkisini tekrar doğrular; kaldırılan erişimi korumaz ve bağlantıyı `exit` ile sonlandırır.

`20261103_43`, `users.role` CHECK kısıtını genişletir, süper yönetici e-posta kısıtını ekler ve yalnız tanımlı mevcut hesabın rolünü yükseltir. Yeni tablo veya izin kopyası oluşturmaz. Parola özetleri, oturumlar, kişisel bağlantılar ve mevcut açık SSH atamaları korunur; yönetici hesaplarına SSH yetkisi eklenmez. Geri alma süper yöneticiyi SSH ataması korunmuş yöneticiye çevirir ve eski rol kısıtına döner; eski uygulama sürümüyle birlikte kullanılmalıdır.

PostgreSQL `20261116_03` önceki e-posta ve yerel giriş kısıtlarını kaldırır; kullanıcı rolleri ve oturumlar geçiş sırasında değiştirilmez. Geri dönüş, önceki kısıtlarla uyumlu olmayan süper yönetici ataması varsa durur.
