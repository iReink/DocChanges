# Компоненты и источники

| Компонент | Источник | Лицензия/сведения |
|---|---|---|
| Python standalone | https://github.com/astral-sh/python-build-standalone | Лицензии Python и сборки в поставке |
| uv 0.13.6 | https://github.com/astral-sh/uv | MIT / Apache 2.0 |
| LibreOffice Portable 26.2.4 | https://download.documentfoundation.org/libreoffice/portable/26.2.4/ | MPL 2.0 и лицензии компонентов в поставке |
| 7-Zip 24.08 x64 | https://www.7-zip.org/ | GNU LGPL, BSD и ограничения unRAR; полный текст в vendor/7zip/License.txt |
| PDF.js 5.4.296 | https://github.com/mozilla/pdf.js | Apache 2.0, vendor/pdfjs/LICENSE |
| Noto Sans | https://github.com/notofonts/noto-fonts | SIL Open Font License |
| multilingual MiniLM | https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | Apache 2.0 |
| GLiNER multi v2.1 | https://huggingface.co/urchade/gliner_multi-v2.1 | Apache 2.0 |
| mDeBERTa v3 base, tokenizer/config | https://huggingface.co/microsoft/mdeberta-v3-base | MIT |

7-Zip поставляется без изменений для извлечения App/libreoffice из portable-архива. Исходный код версии 24.08 доступен у автора: https://www.7-zip.org/a/7z2408-src.7z . Установленная на целевом ПК копия 7-Zip не требуется. Архив LibreOffice не запускается как графический установщик.

Версии Python-зависимостей закреплены в requirements-*.lock; лицензионные файлы сохраняются установленными пакетами. Ревизии моделей — config/models.json. SHA-256 uv и конвертера, SHA-512 PDF.js и SHA-256 шрифта закреплены в установочных скриптах. Хеши локального распаковщика — vendor/7zip/manifest.json.

Постоянный конвертер использует поставляемый LibreOffice Python и приватный UNO pipe. Справочные источники: [параметры запуска LibreOffice](https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html), [режим NEVER_EXECUTE для макросов](https://api.libreoffice.org/docs/idl/ref/namespacecom_1_1sun_1_1star_1_1document_1_1MacroExecMode.html), [фильтры преобразования](https://help.libreoffice.org/latest/en-US/text/shared/guide/convertfilters.html). Новые зависимости из сети для UNO не устанавливаются.
