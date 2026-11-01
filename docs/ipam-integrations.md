# VLAN tabanlı IP adres yönetimi

## Kalıcı veri sözleşmesi — 1 Kasım 2026

IP adres yönetimi ve Envanter ayrı menüler ve ayrı yazma akışlarıdır. Bu sözleşme proje sahibinin açık yeni talebi olmadan değiştirilemez. IPAM yalnızca VLAN içindeki IP kayıtlarını yönetir; bir IP gözlemi cihaz envanterine veya Komşuluklar'a kayıt eklemez. Envanter → Ağ keşfi, IPAM taramasını tetiklemez ve keşif gözlemleri IPAM alanlarını beslemez.

| IP alanı | Otomatik kaynak |
| --- | --- |
| Hostname | VLAN'da seçili DNS sunucusu; seçim yoksa sistem çözümleyicisi, PTR |
| MAC | Aynı VRF ve VLAN CIDR'ına doğrudan bağlı gateway arayüzünün ARP/NDP tablosu |
| Bağlı cihaz / Port | Bağlantı → Komşuluklar'ın güncel LLDP/CDP kanıtı; gateway MAC'i ile VLAN'a ait switch FDB eşleştirmesi; VMware VM'lerinde entegrasyonun doğruladığı sanal switch/NIC portu |
| İşletim sistemi | Yönetim → Entegrasyonlar → VMware |

DHCP kiralamaları/rezervasyonları IP kaydı ve VMware NIC eşleşmesi için yardımcı kanıttır. DHCP ve VMware isimleri DNS yerine; DHCP/VMware MAC'i gateway MAC'i yerine; cihaz adına bakılarak tahmin edilmiş bir işletim sistemi VMware yerine gösterilmez. Manuel hostname/OS notları ayrı `managed` alanında korunur; otomatik alanların kaynağını değiştirmez. Kaynağı olmayan otomatik değer boştur.

VMware sanal makinesi olduğu güncel eşleşmeyle doğrulanan IP adreslerinde Kabinet no `Sanal` gösterilir. Bu türetilmiş değer liste, ayrıntı ve düzenleme ekranında aynıdır; manuel kabinet kaydı korunur. Süresi dolmuş veya gateway MAC ile çelişen VMware gözlemi bu gösterimi oluşturmaz.

## Bağlantı eşleştirmesi

- IPAM okuması, envanterdeki aktif switch/router/firewall cihazlarının kayıtlı SNMP profillerini kullanır. Yeni erişim profili veya ağ keşfi kapsamı istemez. Okuma worker'dadır; envanter alanlarını, arayüzleri veya komşulukları değiştirmez. Ayrı `ipam_network` gözlemleri kullanılır; eski `discovery` gözlemleri bağlantıya temel olmaz.
- Gateway arayüzü, IP-MIB arayüz adresi/prefix kanıtıyla VLAN CIDR'ını kapsamalıdır; IPAM, bağlı gateway ağının bir alt bloğunu yönetebilir. FortiOS'un VDOM içeren adres indeksleri, ham dört oktetlik adres/maskeleri ve uzunluk okteti olmayan prefix RowPointer biçimi açık alan/ifIndex kanıtıyla çözülür. Normal bir hostun ARP tablosu kaynak değildir. Aynı IP için birden fazla gateway MAC'i varsa MAC ve kesin bağlantı boş bırakılır; kanıtlar ayrıntıda gösterilir.
- Q-BRIDGE `dot1qTpFdbPort` içindeki FDB kimliği VLAN numarası kabul edilmez. `dot1qVlanFdbId` ile VLAN → FDB kimliği, ardından bridge port → ifIndex → arayüz adı zinciri izlenir. Paylaşılan FDB, eksik eşleme, tamamlanmamış tablo, kapalı veya kimliği çözülemeyen port bağlantı olarak seçilmez.
- Komşuluklarda yalnızca güncel, silinmemiş ve envanterdeki kaynak cihaza ait kayıt kullanılır. Uzak IP veya tanımlı LLDP MAC alt türü eşleşmelidir. Ad/hostname benzerliği ve kullanıcı tarafından değiştirilmiş görünen etiket kimlik kanıtı değildir.
- Uplink portları ve birden çok MAC taşıyan transit portlar uç cihazın fiziksel portu diye gösterilmez. Son switch seçimi cihaz adı veya tür sıralamasıyla yapılmaz.
- Birden çok bağımsız port adayı varsa seçim yapılmaz. Ortak, geçerli LLDP chassis UUID'si veya aynı cihazdaki aynı LAG kimliğiyle kanıtlanan çoklu NIC/port bağlantıları birlikte gösterilebilir.
- Güncellik süresi VLAN'ın keşif aralığının iki katıdır; 5 dakika–24 saat arasında sınırlandırılır. Daha yeni boş/başarısız okuma eski pozitif eşleşmeyi geçersiz kılar. IPAM'dan yeni komşuluk üretilemez; kullanıcı tarafından silinen komşuluk yeniden oluşturulmaz.
- VMware IP/NIC kaydı gateway MAC'iyle çelişirse o VM'nin işletim sistemi/bağlantısı o IP'ye atanmaz. VMware guest IP bildirmese de tekil NIC, gateway MAC'iyle eşleştirilebilir; gateway kanıtı yoksa DHCP yardımcı eşleşmesi kullanılabilir. Aynı IP için birden fazla VM/NIC bağlantısı bulunursa keyfi seçim yapılmaz. Fiziksel host uplink'i VM'nin kendi portu olarak sunulmaz.

IP ayrıntıları kaynak, cihaz, port/MAC, gözlem zamanı ve belirsizlik nedenini gösterir. HTTP sorgusu ağ işlemi yapmaz; ilgili cihazlar ve son gözlemler toplu okunur. Yetkilendirilmiş yanıtların kısa süreli önbelleği değişiklik bildirimleriyle geçersiz kılınır.

Protokol temelleri: [IP-MIB (RFC 4293)](https://www.rfc-editor.org/rfc/rfc4293.html), [Q-BRIDGE-MIB (RFC 4363)](https://www.rfc-editor.org/rfc/rfc4363.html). Davranış testleri: `test_ipam_source_contract.py`, `test_ipam_network_worker.py`, `test_connection_inventory_boundary.py`.

## VLAN ve zamanlama

IP adres yönetimi → VLAN alanları, CIDR, VRF, DNS, kurum/lokasyon ve zamanlama ayarlarının sahibidir. Yeni VLAN/IP bloğu değişikliği aynı transaction içinde `ipam_discover` işi oluşturur. IPv4 en çok 65.536 adres, 32 eşzamanlı probe ile taranır; IPv6 uzayı gezilmez, bilinen adresler kontrol edilir.

VLAN ayrıntısındaki **Tara ve eşleştir**, yeni VLAN kaydının otomatik başlattığı `ipam_discover` akışıyla aynıdır. Etkin iş varsa aynı iş döner; buton işlem boyunca devre dışıdır. VLAN yeniden açıldığında son tarama ve aşaması `GET /api/v1/ipam/vlans/{id}/scan` ile görünür.

Tarama ping/DNS kontrolünden sonra gateway/switch kaynaklarını en çok dört eşzamanlı okumayla toplar. Her cihazda taşıma yeniden denemesi ve 180 saniyelik toplam protokol sınırı vardır. Ardından DHCP eşitlemesini, sonra VMware eşitlemesini bekler; DHCP'nin oluşturduğu VMware işi yeniden kullanılır. Her kaynak aşamasında en çok 15 dakika bekler; başarısız, iptal edilmiş, bulunamayan veya zaman aşımına uğrayan bağımlılık kısmi sonuçtur. Ana görev kaynaklar kuyruğa konunca tamamlandı sayılmaz. Kaynak okumalarından sonra yeni/ICMP yanıtı vermeyen kayıtların DNS kontrolü tamamlanır, cihaz/port kanıtları çözülür ve alan başına eşleşme sayısı kaydedilir.

Envanter keşfi ve IPAM taraması birlikte en fazla iki worker yuvası kullanır; kalan yuvalar bağımlı entegrasyonlar ve kısa görevler için açıktır. Böylece kaynak bekleyen taramalar worker'ı kilitlemez. İptal beklemeyi ve sürmekte olan IPAM okumalarını durdurur; başka taramalarla paylaşılabilen entegrasyon işi otomatik iptal edilmez. Aynı iş yeniden başlarsa IPAM ağ gözlemleri yinelenmez; güncel, başarılı ve bağlantı/profil sürümü aynı okumalar korunarak kalan cihazlardan devam edilir. Başarısız/eski okumalar veya değişen erişim bilgileri yeniden okunur. Yeni bir tarama işi önceki işin okumalarını atlamaz. Ping ve yeni IP keşif zamanlamaları ayrı kalır. Ping sonucu yalnızca güncel ICMP gözlemidir; VM güç durumu değildir.

## Entegrasyonlar

Yönetim → Entegrasyonlar yalnızca VMware vCenter ve Microsoft Windows DHCP içerir. Entegrasyonlar bütün IPAM VLAN'larına hizmet eder; ayrı yetkili ağ blokları listesi yoktur. Switch/router/gateway erişimi mevcut envanter cihazının şifreli profiliyle yapılır; yinelenen switch entegrasyonu oluşturulmaz.

VMware IP/MAC, işletim sistemi, güç durumu, VM/NIC ve sanal switch/port grubu kanıtını; DHCP rezervasyon ve aktif kiralamaları sağlar. Aynı adres farklı VRF'lerde belirsizse otomatik VLAN ataması yapılmaz. Başarılı eşitleme, VLAN'daki kayıtlı IP'ler için ping/DNS kontrolünü kuyruğa alır. Sırlar API ve loglara dönmez.

## Silme ve menü sınırı

VLAN silme önizlemesi IP sayısını gösterir. Silme VLAN'ın ping/keşif işlerini iptal eder; VLAN ve IP gözlemlerini kaldırır. Envanter ve entegrasyon kayıtları korunur. IPAM'a ait sunucular Bağlantı cihaz listesine taşınmaz. Ortak kurum/lokasyon ve kabinet tanımları kullanılmaya devam eder.
