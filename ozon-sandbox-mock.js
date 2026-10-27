#!/usr/bin/env node
'use strict';
/**
 * Локальный мок Ozon Seller API (товары, остатки, цены, склады, импорт, аналитика).
 * Без зависимостей: node ozon-sandbox-mock.js
 *
 * ENV:
 *   PORT=8080     порт
 *   COUNT=200     сколько товаров (минимум 13)
 *   SEED=42       сид генератора (одинаковый сид = одинаковые данные)
 *   DRIFT=1       раз в 15 с случайно менять FBS-остатки (имитация продаж/поставок)
 *
 * Первые 13 товаров совпадают с твоим списком из песочницы (product_id, offer_id, sku, флаги).
 * Формат ответов собран по документации Ozon Seller API по памяти: сверь DTO своего сервиса.
 */
const http = require('http');

const PORT = Number(process.env.PORT || 8080);
const COUNT = Math.max(13, Number(process.env.COUNT || 200));
const DRIFT = process.env.DRIFT === '1';

function rng(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = rng(Number(process.env.SEED || 42));
const ri = (a, b) => a + Math.floor(rand() * (b - a + 1));
const pick = (arr) => arr[ri(0, arr.length - 1)];

const WAREHOUSES = [
  { warehouse_id: 1001, name: 'Тестовый склад Москва' },
  { warehouse_id: 1002, name: 'Тестовый склад Ярославль' },
];

// product_id, offer_id, has_fbo, has_fbs, archived, sku (из твоего ответа песочницы)
const SEED13 = [
  [1000123457, 'a6701450', true, false, false, 5082220452],
  [1000123458, '06401C30', false, true, false, 5025708100],
  [1000123459, 'W7761769-38', true, true, false, 5013878354],
  [1000123460, 'M7251916-42', false, false, false, 5008284021],
  [1000123461, 'M7251855-45', false, true, false, 5008282520],
  [1000123462, '48701950', false, false, true, 4800675119],
  [1000123463, 'a8421f62', true, false, false, 5077332211],
  [1000123464, '4F0A9E1B', false, true, false, 4809672345],
  [1000123465, 'W3312020-38', true, true, false, 5004417882],
  [1000123466, 'M8527144-50', false, true, false, 5069203344],
  [1000123467, 'b3d19c87', false, true, false, 4870441198],
  [1000123468, '0F3B62C1', false, false, false, 5021998760],
  [1000123469, 'G7001880-46', true, false, false, 5098112347],
];

const NOUNS = ['Кружка', 'Футболка', 'Рюкзак', 'Наушники', 'Чехол для телефона', 'Настольная лампа',
  'Плед', 'Бутылка для воды', 'Блокнот', 'Кроссовки', 'Часы', 'Термос', 'Коврик для йоги',
  'Powerbank', 'Мышь беспроводная', 'Зарядное устройство', 'Органайзер', 'Шапка', 'Перчатки', 'Полотенце'];
const ADJS = ['Классический', 'Тестовый', 'Премиум', 'Лёгкий', 'Компактный', 'Универсальный', 'Спортивный', 'Домашний'];
const CATS = [[17028973, 91565], [17027494, 91001], [17031000, 92340], [17029555, 90812]];

function makeProduct(i, seed13) {
  const noun = pick(NOUNS), adj = pick(ADJS);
  const price = ri(20, 900) * 10 - 1;
  const [cat, type] = pick(CATS);
  const fboPresent = rand() < 0.3 ? 0 : ri(1, 300);
  const p = {
    product_id: 1000123457 + i,
    offer_id: `T${String(i).padStart(4, '0')}-${ri(36, 50)}`,
    sku: 5100000000 + i * 37 + ri(0, 30),
    name: `${adj} ${noun.toLowerCase()} №${i + 1}`,
    description: `${noun}: ${adj.toLowerCase()} вариант для тестов. Артикул модели ${ri(1000, 9999)}, материал и цвет — на ваш вкус. Тестовое описание товара №${i + 1}.`,
    price,
    old_price: Math.round(price * 1.25),
    min_price: Math.round(price * 0.8),
    net_price: Math.round(price * 0.55),
    vat: '0',
    barcode: '2' + String(ri(0, 999999999999)).padStart(12, '0'),
    created_at: new Date(Date.UTC(2026, ri(0, 8), ri(1, 28), ri(0, 23), ri(0, 59))).toISOString(),
    description_category_id: cat,
    type_id: type,
    archived: rand() < 0.04,
    is_discounted: rand() < 0.08,
    fbo: { present: fboPresent, reserved: fboPresent > 0 ? Math.min(fboPresent, ri(0, 5)) : 0 },
    fbs: {},
  };
  for (const w of WAREHOUSES) {
    const present = rand() < 0.4 ? 0 : ri(1, 150);
    p.fbs[w.warehouse_id] = { present, reserved: present > 0 ? Math.min(present, ri(0, 4)) : 0 };
  }
  if (seed13) {
    const [pid, offer, hasFbo, hasFbs, archived, sku] = seed13;
    p.product_id = pid; p.offer_id = offer; p.sku = sku; p.archived = archived;
    if (hasFbo && p.fbo.present === 0) p.fbo.present = ri(1, 80);
    if (!hasFbo) p.fbo = { present: 0, reserved: 0 };
    if (hasFbs && !Object.values(p.fbs).some((s) => s.present > 0)) p.fbs[1001] = { present: ri(1, 80), reserved: 0 };
    if (!hasFbs) for (const k of Object.keys(p.fbs)) p.fbs[k] = { present: 0, reserved: 0 };
  }
  return p;
}

const products = [];
for (let i = 0; i < COUNT; i++) products.push(makeProduct(i, SEED13[i]));

const hasFbo = (p) => p.fbo.present > 0;
const fbsSum = (p, f) => Object.values(p.fbs).reduce((a, s) => a + s[f], 0);
const hasFbs = (p) => fbsSum(p, 'present') > 0;
const imagesOf = (p) => [`https://example.com/img/${p.product_id}.jpg`];

function applyFilter(filter) {
  filter = filter || {};
  const vis = filter.visibility || 'ALL';
  let list = products;
  if (vis === 'ARCHIVED') list = list.filter((p) => p.archived);
  else if (vis !== 'ALL') list = list.filter((p) => !p.archived);
  if (filter.offer_id && filter.offer_id.length) list = list.filter((p) => filter.offer_id.includes(p.offer_id));
  if (filter.product_id && filter.product_id.length) {
    const ids = filter.product_id.map(String);
    list = list.filter((p) => ids.includes(String(p.product_id)));
  }
  return list;
}

const stocksOf = (p) => [
  { present: p.fbo.present, reserved: p.fbo.reserved, sku: p.sku, type: 'fbo' },
  { present: fbsSum(p, 'present'), reserved: fbsSum(p, 'reserved'), sku: p.sku, type: 'fbs' },
];

const tasks = new Map();
let taskSeq = 1000;

const routes = {
  'POST /v3/product/list': (b) => {
    const list = applyFilter(b.filter);
    const limit = Math.min(Number(b.limit) || 100, 1000);
    const idx = b.last_id ? list.findIndex((p) => String(p.product_id) === String(b.last_id)) : -1;
    const items = list.slice(idx + 1, idx + 1 + limit);
    return {
      result: {
        items: items.map((p) => ({
          product_id: p.product_id, offer_id: p.offer_id,
          has_fbo_stocks: hasFbo(p), has_fbs_stocks: hasFbs(p),
          archived: p.archived, is_discounted: p.is_discounted, quants: [], sku: p.sku,
        })),
        total: list.length,
        last_id: items.length ? String(items[items.length - 1].product_id) : '',
      },
    };
  },

  'POST /v3/product/info/list': (b) => {
    const offer = b.offer_id || [], pid = (b.product_id || []).map(String), sku = (b.sku || []).map(String);
    const items = products.filter((p) => offer.includes(p.offer_id) || pid.includes(String(p.product_id)) || sku.includes(String(p.sku)));
    return {
      items: items.map((p) => ({
        id: p.product_id, name: p.name, offer_id: p.offer_id, sku: p.sku,
        barcodes: [p.barcode], buybox_price: '',
        description_category_id: p.description_category_id, type_id: p.type_id,
        created_at: p.created_at, images: imagesOf(p), primary_image: imagesOf(p),
        currency_code: 'RUB', price: String(p.price), old_price: String(p.old_price), min_price: String(p.min_price),
        vat: p.vat, visible: !p.archived, is_archived: p.archived, is_discounted: p.is_discounted,
        stocks: { has_stock: hasFbo(p) || hasFbs(p), stocks: stocksOf(p).map((s) => ({ present: s.present, reserved: s.reserved, sku: s.sku, source: s.type })) },
        statuses: { status: 'price_sent', status_name: 'Продаётся', is_created: true },
      })),
    };
  },

  'POST /v1/product/info/description': (b) => {
    const p = products.find((x) => String(x.product_id) === String(b.product_id) || x.offer_id === b.offer_id);
    if (!p) throw httpErr(404, 'PRODUCT_NOT_FOUND');
    return { result: { id: p.product_id, offer_id: p.offer_id, name: p.name, description: p.description } };
  },

  'POST /v4/product/info/stocks': (b) => {
    const list = applyFilter(b.filter);
    const limit = Math.min(Number(b.limit) || 100, 1000);
    const start = b.cursor ? Number(b.cursor) : 0;
    const slice = list.slice(start, start + limit);
    const next = start + slice.length;
    return {
      cursor: next >= list.length ? '' : String(next),
      items: slice.map((p) => ({ offer_id: p.offer_id, product_id: p.product_id, stocks: stocksOf(p) })),
      total: list.length,
    };
  },

  'POST /v5/product/info/prices': (b) => {
    const list = applyFilter(b.filter);
    const limit = Math.min(Number(b.limit) || 100, 1000);
    const start = b.cursor ? Number(b.cursor) : 0;
    const slice = list.slice(start, start + limit);
    const next = start + slice.length;
    return {
      cursor: next >= list.length ? '' : String(next),
      items: slice.map((p) => ({
        offer_id: p.offer_id, product_id: p.product_id, acquiring: Math.round(p.price * 0.015),
        price: { currency_code: 'RUB', price: p.price, old_price: p.old_price, min_price: p.min_price, net_price: p.net_price, retail_price: 0, vat: Number(p.vat) },
      })),
      total: list.length,
    };
  },

  'POST /v1/product/info/stocks-by-warehouse/fbs': (b) => {
    const skus = (b.sku || []).map(String);
    const out = [];
    for (const p of products.filter((x) => skus.includes(String(x.sku)))) {
      for (const w of WAREHOUSES) {
        const s = p.fbs[w.warehouse_id];
        out.push({ present: s.present, reserved: s.reserved, product_name: p.name, sku: p.sku, warehouse_id: w.warehouse_id, warehouse_name: w.name });
      }
    }
    return { result: out };
  },

  'POST /v1/warehouse/list': () => ({
    result: WAREHOUSES.map((w) => ({ warehouse_id: w.warehouse_id, name: w.name, is_rfbs: false, status: 'created', is_able_to_set_price: true })),
  }),

  // Обновление FBS-остатков: меняет состояние мока, чтобы можно было проверять синхронизацию
  'POST /v2/products/stocks': (b) => ({
    result: (b.stocks || []).map((s) => {
      const p = products.find((x) => x.offer_id === s.offer_id || String(x.product_id) === String(s.product_id));
      const errors = [];
      if (!p) errors.push({ code: 'PRODUCT_NOT_FOUND', message: 'product not found' });
      else if (!p.fbs[s.warehouse_id]) errors.push({ code: 'WAREHOUSE_NOT_FOUND', message: 'warehouse not found' });
      else if (!(Number(s.stock) >= 0)) errors.push({ code: 'INVALID_STOCK', message: 'stock must be >= 0' });
      else p.fbs[s.warehouse_id].present = Number(s.stock);
      return { offer_id: s.offer_id, product_id: s.product_id, warehouse_id: s.warehouse_id, updated: errors.length === 0, errors };
    }),
  }),

  'POST /v1/product/import/prices': (b) => ({
    result: (b.prices || []).map((x) => {
      const p = products.find((y) => y.offer_id === x.offer_id || String(y.product_id) === String(x.product_id));
      if (!p) return { offer_id: x.offer_id, product_id: x.product_id, updated: false, errors: [{ code: 'PRODUCT_NOT_FOUND', message: 'product not found' }] };
      if (x.price) p.price = Number(x.price);
      if (x.old_price) p.old_price = Number(x.old_price);
      if (x.min_price) p.min_price = Number(x.min_price);
      return { offer_id: p.offer_id, product_id: p.product_id, updated: true, errors: [] };
    }),
  }),

  // Создание/обновление товаров (упрощённо: без валидации категорий и атрибутов)
  'POST /v3/product/import': (b) => {
    const results = [];
    for (const it of b.items || []) {
      let p = products.find((x) => x.offer_id === it.offer_id);
      if (!p) {
        p = makeProduct(products.length, null);
        p.product_id = Math.max(...products.map((x) => x.product_id)) + 1;
        p.offer_id = it.offer_id;
        products.push(p);
      }
      if (it.name) p.name = it.name;
      if (it.description) p.description = it.description;
      if (it.price) p.price = Number(it.price);
      if (it.old_price) p.old_price = Number(it.old_price);
      results.push({ offer_id: p.offer_id, product_id: p.product_id, status: 'imported', errors: [] });
    }
    const id = ++taskSeq;
    tasks.set(id, results);
    return { result: { task_id: id } };
  },

  'POST /v1/product/import/info': (b) => {
    const r = tasks.get(Number(b.task_id));
    if (!r) throw httpErr(404, 'TASK_NOT_FOUND');
    return { result: { items: r, total: r.length } };
  },

  // Псевдо-статистика: детерминированная от product_id. dimension: sku (по умолчанию) или без разбивки
  'POST /v1/analytics/data': (b) => {
    const metrics = b.metrics || ['revenue', 'ordered_units'];
    const limit = Math.min(Number(b.limit) || 100, 1000);
    const offset = Number(b.offset) || 0;
    const row = (p) => {
      const units = (p.product_id * 7919) % 41;
      return metrics.map((m) => {
        if (m === 'ordered_units') return units;
        if (m === 'revenue') return units * p.price;
        if (m === 'hits_view' || m === 'hits_view_search' || m === 'hits_view_pdp') return units * 37 + ((p.product_id * 31) % 500);
        return (p.product_id * 13) % 100;
      });
    };
    const dims = b.dimension || ['sku'];
    let data;
    if (dims.includes('sku')) {
      data = products.slice(offset, offset + limit).map((p) => ({ dimensions: [{ id: String(p.sku), name: p.name }], metrics: row(p) }));
    } else {
      const sums = metrics.map(() => 0);
      products.forEach((p) => row(p).forEach((v, i) => { sums[i] += v; }));
      data = [{ dimensions: [], metrics: sums }];
    }
    const totals = metrics.map((_, i) => products.reduce((a, p) => a + row(p)[i], 0));
    return { result: { data, totals }, timestamp: new Date().toISOString() };
  },
};

function httpErr(status, message) {
  const e = new Error(message); e.status = status; return e;
}

if (DRIFT) {
  setInterval(() => {
    for (let k = 0; k < 10; k++) {
      const p = pick(products);
      if (p.archived) continue;
      const s = p.fbs[pick(WAREHOUSES).warehouse_id];
      s.present = Math.max(0, s.present + ri(-3, 3));
    }
  }, 15000);
}

http.createServer((req, res) => {
  let data = '';
  req.on('data', (c) => { data += c; });
  req.on('end', () => {
    const send = (code, obj) => {
      res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(obj));
    };
    const path = req.url.split('?')[0].replace(/\/+$/, '');
    const key = `${req.method} ${path}`;
    console.log(new Date().toISOString(), key);
    if (key === 'GET /health') return send(200, { ok: true, products: products.length });
    const h = routes[key];
    if (!h) return send(404, { code: 5, message: 'Not Found', details: [] });
    let body = {};
    if (data) {
      try { body = JSON.parse(data); } catch (e) { return send(400, { code: 3, message: 'invalid JSON', details: [] }); }
    }
    try { send(200, h(body)); }
    catch (e) { send(e.status || 500, { code: e.status === 404 ? 5 : 13, message: e.message, details: [] }); }
  });
}).listen(PORT, () => console.log(`Ozon mock: http://localhost:${PORT}  products=${products.length} drift=${DRIFT}`));
