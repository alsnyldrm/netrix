# HP 1950 · Comware 7

30 Ekim 2026: `hp_1950` seçeneği cihaz formu, toplu düzenleme ve CSV/XLSX aktarımına eklendi. Kullanıcının doğruladığı model 1950'dir. Mevcut cihaz adaptörleri değiştirilmez; şema değişikliği yoktur.

HP/HPE OfficeConnect 1950, Comware 7 kullanır. Resmi HPE belgeleri sınırlı CLI ve özel yetki gerektiren `xtd-cli-mode` komutunu belirtir. Bu seçenek 1910/1920/1920S/1930 ailelerinin tamamı için uyumluluk iddiası değildir.

HPE kullanıcı kılavuzu genişletilmiş CLI'ı destek personelinin sorun giderme modu olarak tanımlar; müşteri ağlarında rutin kullanımına üretici desteği vermez. NETRIX bu modu yalnızca SSH profiline ayrı parolası girilmişse kullanır. Kılavuzdaki `Switch to extended CLI mode? [Y/N]:` ve `Password:` istemleri, satıra bölünmüş/parçalı yanıtlar dahil işlenir. Mod yalnızca o oturumda geçerlidir.

## Kullanım ve davranış

1. Cihazda **Konfigürasyon adaptörü → HP 1950 · Comware 7** seçilir. Kayıtlı SSH profili, portu ve host anahtarına güven tercihi kullanılır.
2. Sınırlı CLI kullanılıyorsa **Yönetim → Erişim kasası → SSH profili → Genişletilmiş CLI parolası** doldurulur. Bu isteğe bağlı alan SSH giriş parolasından ayrıdır. Mevcut kasa davranışı gereği profil düzenlenirken SSH giriş bilgileri de yeniden girilir. Yeni sır mevcut uygulama şifrelemesiyle saklanır; API/audit yanıtları ve CSV/XLSX dışa aktarımları parolayı açığa çıkarmaz. Parola değiştirme ve silme profilin mevcut güncelleme akışını kullanır.
3. Tek PTY oturumunda `<Sysname>` istemi beklenir. `screen-length disable` yalnızca o oturumun sayfalamasını kapatır. Bu komut reddedilirse ve profil genişletilmiş CLI parolası içeriyorsa `xtd-cli-mode`, onay ve parola istemleri sınırlı adımlarla işlenir. NETRIX içinde üretici parolası gömülü değildir; sır yalnızca parola isteminden sonra gönderilir. Eksik/yanlış sırda yedek başarı olarak gösterilmez. Kalıcı cihaz konfigürasyonu değiştirilmez.
4. Kimlik için `display version` okunur; sınırlı oturumda kimlik okuması `summary` ile denenebilir. Model/üretici yalnızca yanıttaki ürün bilgisinden çıkarılır. Yedek ve aktif konfigürasyon karşılaştırması `display current-configuration` kullanır.
5. Süre/boyut sınırları, CLI hatası, sayfalama ve eksik çıktı kontrolleri uygulanır. Yedek için `version`, `sysname`, bölüm ayırıcıları ve son `return` satırı aranır. Çıktı mevcut şifreli yedek motoruna gider; görüntüleme/karşılaştırmada sırlar maskelenir. Bu yapısal doğrulama donanımda geri yükleme garantisi değildir.

SNMPv2c/v3 testleri ve izleme adaptörden bağımsızdır. SSH bağlantı testi oturum kimlik doğrulamasını sınar; başarılı SSH testi genişletilmiş CLI yetkisini veya yedekleme desteğini kanıtlamaz. Test düğmesinin etkinliği kayıtlı profil, aktif cihaz ve yetkili kapsam kontrollerine bağlıdır.

Gerçek HP 1950 donanımı üzerinde doğrulama yapılmadı; doğrulamalar sahte CLI yanıtları ve yerel API/tarayıcı ile yürütülür.

## Resmi kaynaklar

- [HPE OfficeConnect 1950 kullanıcı kılavuzu — xtd-cli-mode, s.154 (HPE belgesinin kopyası)](https://www.intesiscon.com/ficheros/manuales-tecnicos/251-HPE-c04657809-HPE-OfficeConnect-1950-Switch-Series-User-Guide.pdf).
- [HPE 1950'nin Comware 7 işletim sistemi ve model listesi](https://support.hpe.com/hpesc/public/docDisplay?docId=c05270839&docLocale=en_US).
- [HPE OfficeConnect 1950 sınırlı CLI ürün bilgisi](https://support.hpe.com/hpesc/public/docDisplay?docId=c04686146&docLocale=en_US&page=GUID-F3BA82F7-A27B-4C0C-A9CB-FA621616A624.html).
- [HPE 1950 komut listesi: summary ve özel yetki gerektiren xtd-cli-mode](https://support.hpe.com/hpesc/public/docDisplay?docId=sf000057009en_us&page=index.html).
- [HPE Comware 7 display current-configuration referansı](https://support.hpe.com/hpesc/public/api/document/c05030686).
- [HPE Comware screen-length disable oturum kapsamı](https://support.hpe.com/hpesc/public/api/document/c04406895).
- [H3C Comware display version komutu ve ürün/uptime alanı](https://www.h3c.com/en/d_202406/2194639_294551_0.htm).
