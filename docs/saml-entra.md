# NETRIX SAML / Microsoft Entra ID

Süper yönetici **Yönetim → SAML / Microsoft Entra ID** ekranından ayarları düzenler. Yerel parola girişi çalışmaya devam eder. Yeni kurulumda SAML kapalıdır. EMC'deki işletim uygulaması ve sertifikası mevcut olabilir; NETRIX için ayrı Enterprise Application kaydı kullanın.

1. Entra yönetim merkezinde **Enterprise applications → [NETRIX] → Single sign-on → SAML** ekranını açın. NETRIX ekranındaki değerleri kullanın:

   | Entra alanı | Varsayılan NETRIX değeri |
   | --- | --- |
   | Identifier (Entity ID) | `https://netrix.fbu.edu.tr/api/v1/auth/saml/metadata` |
   | Reply URL (Assertion Consumer Service) | `https://netrix.fbu.edu.tr/api/v1/auth/saml/acs` |
   | Sign on URL | `https://netrix.fbu.edu.tr/api/v1/auth/saml/login` |

   Entra XML dosyası istiyorsa NETRIX’te **SP metadata XML indir** ile `netrix-saml-metadata.xml` dosyasını alın. `/api/v1/auth/saml/metadata` XML URL’si olarak da kullanılabilir.

2. Kullanıcıları veya grupları NETRIX Enterprise Application'a atayın. **SAML Signing Certificate** seçeneklerinde SHA-256 ile **Sign SAML assertion** veya **Sign SAML response and assertion** seçin. NETRIX ekranındaki **Microsoft Entra ID Metadata XML URL** alanına Entra’nın **App Federation Metadata URL** değerini yapıştırın ve **Metadata’yı aktar** düğmesini kullanın. Microsoft XML’indeki IdP Entity ID, giriş/çıkış adresleri ve imzalama sertifikaları forma gelir; **SAML ayarlarını kaydet** ile devreye alınır. Manuel kurulum için IdP (Microsoft Entra Identifier), Login URL ve **Certificate (Base64)** değerini de doğrudan girebilirsiniz. IdP Logout URL isteğe bağlı bilgi olarak saklanır; NETRIX'ten çıkış NETRIX oturumunu kapatır.
3. SAML yanıtında e-posta, görünen ad ve Microsoft'un değişmez `http://schemas.microsoft.com/identity/claims/objectidentifier` claim'i bulunsun. Alternatif olarak IdP kalıcı (persistent) NameID gönderebilir. Varsayılan NameID biçimi emailAddress'tir; Microsoft Entra kullanıcı nesne kimliği NETRIX hesabını bağlamak için kullanılır. İmzalanmış yanıtta nesne kimliği ya da kalıcı NameID yoksa hesap oluşturulmaz.
4. İsteğe bağlı **Rol Mapping JSON** örneği: `{"Netrix.Operator": "operator"}`. Uygulama rolü ve grup claim'leri değerlendirilir; geçerli değerler `viewer`, `operator` ve `admin`'dir. Birden fazla eşleşmede en az yetkili rol uygulanır. Eşleşme yoksa salt okunur rolü kullanılır. Süper yöneticinin Ekip & yetkiler'de elle değiştirdiği uygulama rolü, sonraki SAML girişlerinde korunur. SSH yetkisi ayrıca yönetilir.
5. **SAML ile girişi etkinleştir** seçeneğiyle kaydedin. Atanmış bir Entra kullanıcısıyla NETRIX giriş sayfasında **Microsoft Entra ID ile giriş yap** eylemini kullanın. İşlemin başlangıcı NETRIX olmalıdır; Entra'daki uygulama kutucuğu NETRIX Sign on URL'ye yönlendirebilir.

NETRIX, SAML hesaplarını IdP Entity ID ve imzalı değişmez kullanıcı kimliğiyle ayırt eder. Aynı e-postalı bir yerel hesapla otomatik bağ kurulmaz. Ayrılmış süper yönetici hesabı yalnız yerel oturum açar; SAML hesabı yerel parola ile giriş yapamaz. Ayarlar değiştiğinde SAML oturumları kapatılır ve yerel oturumlar korunur. Sertifika yenilendiğinde metadata’yı yeniden aktarın ve kaydedin. Aynı belgede birden fazla imzalama sertifikası bulunabilir; geçerlilik tarihi uygun olanlar doğrulamada kullanılır. SAML yanıtının XML içeriği uygulama günlüklerine yazılmaz.

İstek durumu ACS kapsamlı güvenli çerezle tarayıcıya bağlanır ve Redis'te 10 dakika, tek kullanımlık saklanır. SAML yanıtı için imza, gönderici, hedef ACS, istek ilişkisi, süre ve hedef uygulama doğrulanır. Yalnız ACS, uygulamanın özel CSRF başlığını gerektirmeyen sağlayıcı POST'unu kabul eder. Metadata, yapılandırma tamamlanmadan da alınabilir.

Resmî kaynak: [Microsoft Entra SAML protokolü](https://learn.microsoft.com/en-us/entra/identity-platform/single-sign-on-saml-protocol), [Entra federation metadata](https://learn.microsoft.com/en-us/entra/identity-platform/federation-metadata), [SAML claim referansı](https://learn.microsoft.com/en-us/entra/identity-platform/reference-saml-tokens).
