# Mobility Conductor üzerinden 7205 ACL yönetimi

22 Kasım 2026 araştırması. Yalnız resmi HPE Aruba belgeleri incelendi; bu not canlı cihaza komut uygulandığı veya NETRIX motorunun Conductor desteğinin tamamlandığı anlamına gelmez. Oturum bağlamında Conductor adresi `10.1.0.30`, yönetilen 7205 adresleri `10.1.0.23` ve `10.1.0.24` olarak bildirilmiştir. Gerçek düğüm yolları ve Conductor erişim yetkileri bu araştırmada sorgulanmadı.

## Sonuç

**SSH üzerinden desteklenen yöntem vardır.** SSH oturumu Conductor’a açılır, hedef controller’ın cihaz düğümü seçilir, ACL ve arayüz bağlantıları bu düğümde değiştirilir, ardından kaydedilip yönetilen cihaza aktarılması doğrulanır. Session ACL komutu Conductor yapılandırma modunda belgelenmiştir ve PEFNG lisansı gerektirir. [Session ACL referansı](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/ip-acc-list-sess.htm).

## Hedef düğüm ve okuma komutları

```text
show switches debug
show configuration devices
show configuration node-hierarchy
show configuration unsaved-nodes
cd <DEVICE_NODE_PATH>
pwd
show configuration effective detail
show configuration committed <DEVICE_NODE_PATH>
show configuration pending
```

İlk komutun belgelenmiş çıktısı IP, MAC ve Nodepath alanlarını birlikte içerir. Cihaz eşlemesi ve hiyerarşi çıktılarıyla kontrol edilmelidir. Bir cihazın düğümü doğrudan `/md/<MAC>` olabileceği gibi arada kurumun grup düğümleri de bulunabilir; adres veya MAC kullanılarak yol tahmin edilmemelidir. `configuration device` komutu eşleme oluşturur/değiştirir; mevcut controller’a ACL uygulamak için yeni eşleme oluşturmak gerekmez. [Switch ayrıntıları](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switches.htm), [cihaz eşlemesi](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/conf-devi.htm).

`cd` ve `change-config-node` düğüm bağlamını değiştirir. Yer tutucu, keşfedilen gerçek **cihaz düğümü** ile değiştirilir; genel `/md` veya ortak grup yolu kullanılırsa değişiklik başka cihazları da etkileyebilir. [Düğüm değiştirme](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/change-conf-node.htm).

**Conductor üzerinde `show running-config`, seçilen managed-device düğümünün konfigürasyonu değildir; Conductor’ın kendi konfigürasyonudur.** Yukarıdaki etkin yapılandırma okuması, üst gruptan gelen ve cihazda tanımlanan satırların kaynağını gösterir. Bekleyen değişiklikler henüz commit edilmemiştir; commit işlemi düğüm bazındadır. Aynı alt ağaçta bekleyen değişiklik kısıtı bulunur. Ayrıca sıralamaya bağlı ACL/rol tanımları üst düğümden miras alındığında alt düğümde keyfî olarak override edilemez. [Merkezi yapılandırma ve miras](https://arubanetworking.hpe.com/techdocs/ArubaOS/AOS_8x_WebHelp/Content/arubaos-solutions/config-hierarchy/cent-conf.htm).

NETRIX için sonuç: hedef düğüm ve üst zincirdeki mevcut pending değişiklikler incelenmeli; başka yöneticinin değişiklikleri varsa bunlar NETRIX işiyle commit edilmemelidir. Hedef ACL’nin sahibi olan düğüm belirsizse yazma durmalıdır. Aynı Conductor üzerindeki NETRIX yazmalarını sıralamak, ortak pending/commit durumuna karşı önerilen uygulama kararıdır; üreticinin NETRIX’e özgü bir koşulu değildir.

## ACL oluşturma ve porta bağlama

Aşağıdaki, **hedef cihaz düğümü seçildikten ve mevcut politika doğrulandıktan sonra** kullanılabilecek komut kalıbıdır. Yer tutucular canlı ağ değerleri değildir:

```text
configure terminal
ip access-list session <ACL_ADI>
 description "NETRIX-BLACKLIST"
 host <ENGELLENECEK_IPV4> any any deny position 1
 any any any permit
exit
interface gigabitethernet <SLOT>/<MODULE>/<PORT>
 ip access-group session <ACL_ADI>
exit
end
```

Session ACL’de ilk eşleşme uygulanır; deny kuralı izin kuralının önünde olmalıdır. `position` konumu belirtir. Hiç IP bulunmayan ilk hazırlamada deny eklenmez, son izin kuralı bırakılır. Mevcut aynı deny tekrar eklenmez. ACL açıklaması AOS 8.8 ile eklenmiştir; bildirilen 8.10 sürümü bu özellikten sonradır. Arayüz bağlantısı ayrıca uygulanır ve PEFNG lisansı gerektirir. Kullanılacak gerçek fiziksel/LAG arayüzler hedef 7205’ten okunmalıdır. [ACL komutu](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/ip-acc-list-sess.htm), [Ethernet bağlantısı](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/intrfc-gigaether.htm).

Bu akış Syslog, ACL `log` bayrağı, debug ayarı veya managed-device yerel override modu gerektirmez. Bunlar NETRIX’in kapsamına eklenmez.

## Commit ve gerçek cihaza aktarım

Planın pending farkı tekrar incelendikten sonra hedef düğüm bağlamında `write memory` kullanılır. Komut kalıcı kayıt içindir; merkezi modelde commit edilen değişiklik ilgili managed-device’lara dağıtılır. Komutun başarılı dönmesiyle hedef controller’ın uygulamayı bitirmesi aynı şey değildir. [Kaydetme komutu](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/write.htm), [merkezi commit davranışı](https://arubanetworking.hpe.com/techdocs/ArubaOS/AOS_8x_WebHelp/Content/arubaos-solutions/config-hierarchy/cent-conf.htm).

`show switches state complete` ile hedef controller’ın durumu, Config ID ve `UPDATE SUCCESSFUL` sonucu kontrol edilir. Hata incelemesi için `show configuration failure` vardır. Conductor’daki etkin/kaydedilmiş düğüm içeriğine ek olarak, hedef 7205’ten **salt okunur** çalışan konfigürasyon geri okunmalı; ACL kuralları ve bütün amaçlanan port bağlantıları doğrulanmalıdır. Bu son geri okuma NETRIX için önerilen başarı koşuludur. Üreticinin API notu da başarılı yanıtın aktarım başarısını kanıtlamadığını açıkça belirtir. [Senkronizasyon durumu](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switches.htm), [hata/konfigürasyon okuma](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-conf.htm), [üretici izleme açıklaması](https://developer.arubanetworks.com/aos8/docs/monitoring).

## Silme ve uygulama sınırları

Silme de aynı Conductor cihaz düğümünde yapılır: önce ilgili arayüzdeki `ip access-group session <ACL_ADI>` bağlantısı `no` biçimiyle kaldırılır; ardından yalnız NETRIX’e ait session ACL ve kullanılmayan NETRIX yardımcı nesnesi silinir. Kullanıcının başka ACL’si, ortak üst düğüm politikası, yönetim ilişkisi veya cihaz düğümü silinmez. Başka etkin NETRIX grubu aynı ACL’yi kullanıyorsa ortak tanım korunmalıdır. Bağlantı ve ACL komutlarının `no` biçimleri komut referanslarında desteklenir. [Ethernet](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/intrfc-gigaether.htm), [ACL](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/ip-acc-list-sess.htm).

Bir alt düğümde tanımın silinmesi, aynı tanım üst düğümde hâlâ varsa etkin politikadan kaldırıldığı anlamına gelmez. Bu nedenle silme de miras kaynağı, commit ve hedef cihaz geri okumasıyla doğrulanmalıdır. [Kısmi dağıtım ve miras](https://arubanetworking.hpe.com/techdocs/Archived/AOS-8/ArubaOS_81_Web_Help/Content/ArubaFrameStyles/Configuration_Hierarchy/Config_Hierarchy.htm).

NETRIX’te uygulanmadan önce Conductor envanter kaydı/SSH profili, hedef controller–MAC–düğüm eşlemesi, lisans/yetki ve mevcut pending durum doğrulanmalıdır. Bu not bu değerleri uydurmaz; donanımda çalıştırılmış konfigürasyon testi sunmaz.
