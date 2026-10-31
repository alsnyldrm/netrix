# Aruba adaptörleri

30 Ekim 2026 tarihinde resmî HPE Aruba Networking belgeleri incelenerek eklenmiştir.

| Arayüzdeki seçenek | API / CSV / XLSX değeri | İşletim sistemi | Kimlik komutu | Oturum sayfalaması |
| --- | --- | --- | --- | --- |
| Aruba 54xx | `aruba_5400` | ArubaOS-Switch / ProVision (5400zl, 5400R zl2) | `show modules` | `no page` |
| Aruba 2900 | `aruba_2900` | ArubaOS-Switch (2920, 2930F/M) | `show modules` | `no page` |
| Aruba 61xx | `aruba_6100` | AOS-CX (6100) | `show system` | `no page` |
| Aruba 72xx Controller | `aruba_7200` | ArubaOS (7200 Mobility Controller) | `show version` | `no paging` |

54xx seçeneği AOS-S kullanan 5400 ailesi içindir; AOS-CX kullanan yeni 5420 ailesi için değildir. 2900 bir aile etiketi olarak kullanılır; ayrı bir “2900 OS” yoktur.

Tüm seçenekler SSH üzerinde `show running-config` ile çalışan konfigürasyonu okur. Sayfalama komutu ve okuma aynı PTY oturumunda çalışır. Manager/Enable (`#`) yetkisindeki hesap gereklidir; otomatik yetki yükseltme veya kalıcı cihaz ayarı değişikliği yapılmaz. Cihazın kayıtlı SSH portu, profili ve Anahtara güven tercihi kullanılır. SNMPv2c/v3 testleri adaptörden bağımsız olarak atanmış SNMP profili ile yürür.

Yanıtlar süre ve boyut sınırına tabidir. CLI hataları, sayfalama, oturumun beklenmedik kapanması ve konfigürasyon yapısı içermeyen çıktılar yedek olarak kabul edilmez. Ham CLI hata metni kullanıcıya veya loglara taşınmaz. Mevcut şifreli snapshot, karşılaştırma ve zamanlama akışı kullanılır. `show running-config` cihazın gizlediği/parolası maskelenmiş alanları açmaz; tam felaket kurtarma paketi veya geri yükleme garantisi değildir.

Kimlik alanları yalnızca yanıtın chassis, vendor, product name ve model alanlarından çıkarılır. Modül adı veya seçilen adaptör, üretici/model kanıtı sayılmaz; okunamayan alanlarda elle girilen bilgi korunur. Birden fazla farklı chassis modeli varsa model üzerine yazılmaz. Mevcut cihaz türleri arasında Controller bulunmadığından 72xx kimlik okuması mevcut cihaz türünü korur.

Yeni seçenekler mevcut `VARCHAR(20)` adaptör alanına sığar; şema/migration değişikliği gerektirmez. Mevcut cihazların adaptör seçimi otomatik değiştirilmez.

## Test neden kapalı olabilir?

Test öncesinde cihazın arşivlenmemiş ve yaşam döngüsünün aktif olması gerekir. Yönetim IP'si aynı VRF'de etkin bir keşif kapsamında bulunmalı ve kapsamın hariç tutulan adresleri arasında olmamalıdır. Tek cihaz için IPv4 `/32` veya IPv6 `/128` kapsamı kullanılabilir. Profil atanması tek başına kapsam yetkisi vermez. API ve worker bu kontrolü sürdürür; kapsam oluşturulması kendiliğinden tarama başlatmaz.

## Resmî kaynaklar

- [ArubaOS-Switch belge portalı — 5400R, 2920 ve 2930 aileleri](https://arubanetworking.hpe.com/techdocs/AOS-S/DocPortal/Content/home.htm)
- [Aruba 2920, ArubaOS-Switch 16.09 yönetim kılavuzu](https://arubanetworking.hpe.com/techdocs/AOS-Switch/16.09/Aruba%202920%20Management%20and%20Configuration%20Guide%20for%20ArubaOS-Switch%2016.09.pdf)
- [AOS-S show modules ve chassis bilgileri](https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/KB/content/kb/sho-mod.htm)
- [Aruba 2930M/F show running-config](https://arubanetworking.hpe.com/techdocs/AOS-S/16.10/MCG/WC/content/common%20files/sho-run-con.htm)
- [AOS-S no page](https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/YAYB/content/common%20files/dis-inf-you-nee-dia-pro.htm)
- [AOS-CX 10.14 CLI kılavuzu — 6000/6100, page ve show komutları](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.14/PDF/cli_6000-6100.pdf)
- [AOS-CX 10.14 temel bilgiler — 4100i/6000/6100](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.14/PDF/fundamentals_4100i-6000-6100.pdf)
- [7200 Controller ve ArubaOS sürümleri](https://help.centralon-prem.arubanetworks.com/2.5.2/documentation/online_help/content/nms-on-prem/controllers/supported_controllers.htm)
- [ArubaOS show version](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-version.htm)
- [ArubaOS Controller no paging ve show running-config](https://arubanetworking.hpe.com/techdocs/VSG/docs/035-campus-migrate/esp-campus-migrate-072-aos8to10-discovery/)

30 Ekim 2026 düzeltmesi: AOS-S, `no page` sonrasında CRLF yerine ANSI imleç konumlama kodları gönderdiğinde önceki temizleyici komut yankısını istemle birleştiriyordu. İstem bulunamadığı için görev zaman aşımına düşüyordu. İlk terminal sütununa geçiş artık ANSI kodları kaldırılmadan önce satır sınırı olarak korunur; istemin ardından gelen terminal boşlukları kabul edilir.

Bu davranış parçalı sahte SSH yanıtlarıyla regresyon testine alınmıştır. J9851A ve J9850A cihazlarında kayıtlı profil ve yetkili kapsam ile salt okunur SSH denemesi, yapısal doğrulamadan geçen çalışan konfigürasyon çıktısını yaklaşık 3 saniyede aldı. Konfigürasyon içeriği ve sırlar teşhis çıktısına yazılmadı. Diğer Aruba ailelerinin donanım doğrulaması bu sonuçtan çıkarılmaz.

Yedekleme/karşılaştırma görevleri artık zaman aşımı, SSH kimlik doğrulama, host anahtarı, komut ve bağlantı hatalarını sabit, sır içermeyen mesaj ve `error_code` ile ayırır. Zaman aşımında mevcut en fazla üç deneme politikası korunur; eksik çıktı başarı olarak kaydedilmez.

31 Ekim 2026 boşluk düzeltmesi: Ardışık ilk-sütun imleç hareketleri aynı satır sınırı olarak işlenir; her hareket için yeni boş satır eklenmez. İsteğe bağlı `Running configuration:` satırı ardından yerel AOS-S `Configuration Editor; Created on release` başlığı tanınan yedeklerde, komutlar dışındaki boş satırlar okuma/yeni kayıt sırasında temizlenir. Çok satırlı tırnaklı değerler ve PEM blokları korunur; tanınmayan banner ayırıcısı varsa içerik değiştirilmez. FortiOS, AOS-CX ve diğer dosya biçimleri bu AOS-S temizliğine girmez.

Önceden alınmış yedeklerin şifreli asılları değiştirilmez. Görüntüleme, indirme, geçmiş farkı, aktif config karşılaştırması ve worker değişiklik tespiti aynı temizlenmiş içeriği kullanır. Böylece eski terminal boşluklarının giderilmesi kendi başına “Değişenler” kaydı oluşturmaz.
