# Источники

## География

- Natural Earth, Admin 0 Countries, масштаб 1:110m: https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/
- Условия public domain: https://www.naturalearthdata.com/about/terms-of-use/
- Файл: `geojson/ne_110m_admin_0_countries.geojson` из https://github.com/nvkelso/natural-earth-vector
- Зафиксированный commit: `ca96624a56bd078437bca8184e78163e5039ad19`.
- Копия исходника хранится в `data/vendor/`, чтобы сборка не зависела от сети.
- Малые государства: вручную составленные приблизительные точки рядом со столицами; не официальные геодезические данные.

## Игра и редактор

- Официальные новости Age of Clicks, 0.80, раздел Mod containers: https://steamcommunity.com/app/4804480/allnews/
- Мастерская: https://steamcommunity.com/app/4804480/workshop/
- Магазин и разработчик: https://store.steampowered.com/app/4804480/Age_of_Clicks/

Подтверждена общая организация контейнера, но не схема `mod.txt` или файлов сценария. Экспорт игры ещё не исследован.

## Проверка исторического среза

- Хронология расширения НАТО: https://www.nato.int/cps/en/natohq/topics_49212.htm
- История ЕС 2000–2009: https://european-union.europa.eu/principles-countries-history/history-eu/2000-09_en
- История ЕС 2010–2019: https://european-union.europa.eu/principles-countries-history/history-eu/2010-19_en
- История ОДКБ, включая приостановку участия Узбекистана в 2012 году: https://www.odkb-csto.org/30-let-odkb/istoriya/
- Принятие Южного Судана в ООН 14 июля 2011 года: https://press.un.org/en/2011/ga11137.doc.htm

События в `data/events.json` — только первоначальные исторические заготовки. У них пока нет реализованных эффектов, подробных источников или игрового баланса; это задачи следующего этапа.
