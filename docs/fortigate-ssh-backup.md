# FortiGate konfigürasyon yedeği: SSH / SCP

Araştırma tarihi: 30 Ekim 2026. NETRIX kararı: yedekleme yalnızca SSH üzerinden yapılır; SNMP ve REST API yedekleme kaynağı veya hata durumunda alternatif değildir.

## Doğru dosyayı alma

Fortinet'in belgelenmiş indirme yöntemi, SSH taşıması üzerinden SCP ile cihazdaki **`sys_config`** dosyasını almaktır. Yönetim arayüzünde SSH erişimi ve cihazda `admin-scp` açık olmalıdır. OpenSSH 9 ve sonrasında `scp -O`, eski SCP protokolünü seçer; varsayılan SFTP modu aynı işlem değildir. Özel SSH portu `-P` ile belirtilir. [Fortinet SCP yönergesi](https://community.fortinet.com/fortigate-3/technical-tip-how-to-download-a-fortigate-configuration-file-and-upload-a-firmware-file-using-secure-copy-scp-98734)

Yetkili cihaz yöneticisinin gerektiğinde uygulayacağı ön koşul:

```text
config system global
    set admin-scp enable
end
```

Multi-VDOM cihazlarda bu sistem ayarı global yönetim bağlamında uygulanır. NETRIX bu ayarı, arayüz erişimini veya yönetici yetkilerini kendiliğinden değiştirmez. [Fortinet FortiOS Best Practices](https://fortinetweb.s3.amazonaws.com/docs.fortinet.com/v2/attachments/348e176c-a997-11e9-81a4-00505692583a/Best_Practices.pdf)

Yetkili yönetim bilgisayarında örnek indirme komutu; köşeli yer tutucular gerçek değerlerle değiştirilir:

```bash
scp -O -P <SSH_PORT> <SSH_USER>@<FORTIGATE_IP>:sys_config <LOCAL_BACKUP_FILE.conf>
```

Parolayı komut satırına eklemeyin. SSH sunucu anahtarını doğrulayın. NETRIX adaptörü aynı SCP indirmesini SSH istemcisi üzerinden yürütmeli; komut çıktısı yerine gelen dosyanın baytlarını saklamalıdır. SCP ile indirilen dosya cihaz tarafından dosya düzeyinde şifrelenmez; SSH aktarımı şifrelidir. NETRIX saklama şifrelemesi ayrıca uygulanır. [Fortinet SCP yönergesi](https://community.fortinet.com/fortigate-3/technical-tip-how-to-download-a-fortigate-configuration-file-and-upload-a-firmware-file-using-secure-copy-scp-98734)

## Yönetici yetkisi

FortiOS **7.4.4 ve sonrasında** yalnızca okuma yetkisi SCP yedeği için yeterli değildir. Fortinet, `super_admin` veya System → Administrator Users için Read/Write, diğer alanlar için Read yetkisi olan özel profil tarif eder. Makale yöntemin 7.6.0–7.6.3 sürümlerinde de denendiğini belirtir. Hedef sürüm ve kapsam için cihaz yöneticisi profili doğrulamalıdır. [Fortinet sınırlı yetkiyle SCP yedeği](https://community.fortinet.com/fortigate-3/technical-tip-backing-up-the-fortigate-configuration-file-via-scp-with-limited-read-write-permissions-193679)

## Kapsam, başlık ve karşılaştırma

`show` çıktısı, çalıştığı global/VDOM bağlamıyla sınırlıdır ve yedek dosyası başlığını içermez. `show full-configuration` ayrıca varsayılan değerleri gösterir. Bunları `.conf` uzantısıyla kaydetmek belgelenmiş yedek indirme işleminin yerini tutmaz. Fortinet örneğinde gerçek dosyada `#config-version`, `#conf_file_ver`, `#buildno` ve `#global_vdom` başlıkları bulunur. [Fortinet CLI çıktısı ve yedek dosyası ayrımı](https://community.fortinet.com/fortigate-3/technical-tip-how-to-download-fortigate-configuration-file-debug-log-from-gui-and-cli-96675)

`config-version` içindeki **`vdom=1` multi-VDOM modunu belirtir**; tek başına eksik yedek kanıtı değildir. `vdom=0` bekleyerek geçerli multi-VDOM yedeklerini reddetmeyin. [Fortinet VDOM başlığı açıklaması](https://community.fortinet.com/fortigate-3/technical-tip-error-loading-a-converted-global-vdom-configuration-to-a-new-fortigate-177660)

NETRIX aktarımın tamamlanmasını, `#config-version` başlığını, config bloğu ve son `end` satırını kontrol eder; boş, kesilmiş, sayfalanmış veya hatalı çıktı kabul edilmez. Bunlar sözdizimsel kontrollerdir; hesabın tüm VDOM’ları görebildiğini veya geri yüklemenin başarılı olacağını kanıtlamaz. Global/VDOM yetki kapsamını cihaz yöneticisi doğrulamalıdır. `#global_vdom=1` resmi örnekte bulunsa da tek başına tamlık kanıtı olarak kullanılmaz. Aktif konfigürasyon karşılaştırmasında aynı `sys_config` kaynağını kullanın; ham dosyayı koruyun, değişken başlıkların karşılaştırma normalizasyonunu ayrı yapın.

`sys_config` standart konfigürasyon yedeğidir; varsayılan tüm ayarların açıkça yazıldığı `execute backup full-config` çıktısı olarak tanımlanmamalıdır. Fortinet, `full-config` için varsayılan ayarların da dahil edildiğini ayrıca belirtir. [FortiOS yedek türleri](https://docs.fortinet.com/document/fortigate/latest/administration-guide/702257)

## Geri yükleme sınırı

SCP ile geri yükleme ayrı bir yükleme işlemidir ve cihazı yeniden başlatabilir; yedek alma görevi bunu çalıştırmaz. [Fortinet SCP yönergesi](https://community.fortinet.com/fortigate-3/technical-tip-how-to-download-a-fortigate-configuration-file-and-upload-a-firmware-file-using-secure-copy-scp-98734)

Bir konfigürasyon dosyası tüm sertifikalar dahil felaket kurtarma paketiyle eş tutulmamalıdır: Fortinet, VPN sertifikalarının yedeğe alınması için cihaz tarafındaki yedek şifrelemesini şart koşar; ayrıca bazı yerel sertifikalar için ayrı yedek gerektiğini belirtir. NETRIX'in sonradan yaptığı saklama şifrelemesi eksik sertifikaları dosyaya eklemez. [FortiOS 7.4.5 yedek şifrelemesi](https://docs.fortinet.com/document/fortigate/7.4.5/administration-guide/702257), [FortiOS 7.2.0 yerel sertifika kapsamı](https://docs.fortinet.com/document/fortigate/7.2.0/administration-guide/702257/configuration-backups)

Bu araştırmada gerçek cihaza bağlantı, yedek alma veya geri yükleme yapılmadı.
