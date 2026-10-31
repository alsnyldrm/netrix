# Konfigürasyon farkında bölüm bağlamı

1 Kasım 2026 düzeltmesi: FortiOS farkında her değişen satır `config` / `edit` üst bölümleriyle gösterilir. Değişmeyen komşu satırları göstermek yerine, değişen eski/yeni satırlar ve tam bölüm yolu yazılır. Bu metin bir inceleme görünümüdür; cihazda çalıştırılacak komut veya uygulanabilir patch değildir.

Fark hesabı CLI'nın özgün satırlarında yapılır, çıktı daha sonra maskelenir. Böylece iki farklı parolanın aynı maskeleme metnine dönüşüp farktan kaybolması önlenir. FortiOS `set`/`unset` ayar adları korunur; hassas değerler ve çok satırlı özel anahtarlar gizlenir. Tırnaklı çok satırlı değerlerin içindeki `config`/`edit` metinleri gerçek bölüm gibi yorumlanmaz. JSON/XML'nin mevcut bütün belge maskelemesi korunur; maskelenmiş belgeler eşitse özgün içerik değişikliği kısa açıklamayla bildirilir.

Sadece `#conf_file_ver` gibi dosya üstbilgisi değiştiğinde “Yalnızca dosya üstbilgisi değişmiş; kayıtlı konfigürasyon ayarlarında fark yok” yazılır. Değişmeyen `config system global` satırı bu farkın altında gösterilmez. Üstbilgi farkları silinmez veya gizlenmez; yedeklerin şifreli asılları ve değişiklik işaretleri yeniden yazılmaz.

**Fark**, seçilen yedek ile önceki geçerli kayıtlı yedeği karşılaştırır. Pencere önceki yedeğin zamanını ve bu kapsamı açıkça gösterir. **Aktif config ile karşılaştır**, SSH üzerinden cihazı yeniden okuyup seçilen yedekle karşılaştırır; aynı bölüm ve maskeleme mantığını kullanır. Eski tamamlanmış canlı karşılaştırma görevlerinin kaydedilmiş sonuçları yeniden hesaplanmaz; yeni istekler yeni biçimi kullanır.

Üretimde bildirilen 31 Ekim 17:24 yedeği ile bir önceki geçerli yedek incelendi: tek fark dosya sürüm üstbilgisindeydi; ayar değişikliği yoktu. Gerçekte kayıtlı olmayan bir ayar değişikliği gösterilmedi; sırlar/konfigürasyon içeriği teşhis çıktısına alınmadı.

Doğrulama: `tests/test_config_diff_context.py` on bir regresyonla uzak/çok seviyeli üst bölüm, eklenen/silinen/değişen satır, yalnız üstbilgi, hassas değer değişimi, çok satırlı sır ve sahte bölüm metni, kayıtlı ve canlı karşılaştırma API'sini kapsar. `scripts/config_diff_fixture.py` atılabilir SQLite verisi kullanır; `scripts/config_diff_browser_check.py` gerçek fark API'siyle 1440/açık ve 375/koyu pencerelerde üst bölüm + değerler, maskeleme, önceki yedek zamanı, hizalama ve Axe A/AA kontrollerini doğrular. Gerçek ağ sorgusu yapılmaz. Yeni bağımlılık veya şema değişikliği yoktur.
