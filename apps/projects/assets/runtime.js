/*
 * Клиент рантайма.
 *
 * Задача одна: превратить три заглушки в рабочие блоки, если рантайм
 * подключён, и не трогать их, если нет. Второе важнее первого: молча
 * показать корзину, которая не работает, хуже, чем честно написать,
 * что сервера нет (ТЗ п.16.4, ADR-0005).
 *
 * Файл кладётся в пакет как есть и работает без сборки: ни модулей,
 * ни зависимостей. Внешних запросов не делает — только к своему
 * рантайму (п.15.3, п.16.4).
 *
 * Настройка: runtime.json рядом с index.html. Пустой endpoint означает
 * «рантайм не подключён», и скрипт не делает ничего.
 */
(function () {
  'use strict';

  var CONFIG_URL = 'runtime.json';
  var TIMEOUT = 8000;

  /** Тексты ошибок: пользователю нужен ответ, а не код. */
  var MESSAGES = {
    network: 'Сервер магазина не отвечает. Попробуйте позже.',
    blocked: 'Запрос отклонён сервером магазина.',
    rate: 'Слишком много запросов. Подождите минуту.',
    empty: 'Корзина пуста',
    required: 'Заполните имя и телефон и подтвердите согласие.',
    changed: 'Не удалось изменить корзину. '
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function money(value) {
    try {
      return new Intl.NumberFormat('ru-RU').format(value) + ' ₽';
    } catch (e) {
      return String(value) + ' ₽';
    }
  }

  function message(err, fallback) {
    if (err && err.code === 'rate_limited') return MESSAGES.rate;
    if (err && err.status === 403) return MESSAGES.blocked;
    if (err && err.message) return err.message;
    return fallback || MESSAGES.network;
  }

  function note(host, text) {
    var existing = host.querySelector('.rt-note');
    if (!existing) {
      existing = el('p', 'rt-note');
      host.appendChild(existing);
    }
    existing.textContent = text;
  }

  /* --- обмен с рантаймом ------------------------------------------- */

  function Client(config) {
    this.endpoint = String(config.endpoint || '').replace(/\/+$/, '');
    this.siteKey = config.siteKey;
    this.protocolVersion = config.version;
  }

  Client.prototype.request = function (path, options) {
    var init = options || {};
    var headers = { 'X-Site-Key': this.siteKey };
    if (init.body) headers['Content-Type'] = 'application/json';
    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, TIMEOUT) : null;
    return fetch(this.endpoint + path, {
      method: init.method || 'GET',
      credentials: 'same-origin',
      headers: headers,
      body: init.body ? JSON.stringify(init.body) : undefined,
      signal: controller ? controller.signal : undefined
    }).then(
      function (response) {
        if (timer) clearTimeout(timer);
        return response.json().then(
          function (body) {
            if (!response.ok || body.ok === false) {
              var err = new Error(body.message || MESSAGES.network);
              err.status = response.status;
              err.code = body.error;
              throw err;
            }
            return body;
          },
          function () {
            var err = new Error(MESSAGES.network);
            err.status = response.status;
            throw err;
          }
        );
      },
      function () {
        if (timer) clearTimeout(timer);
        var err = new Error(MESSAGES.network);
        err.code = 'network';
        throw err;
      }
    );
  };

  /*
   * Проверка до замены заглушек: при несовпадении версий протокола
   * клиент молча оставил бы заглушку, и покупатель увидел бы её без
   * объяснения. Поэтому причина остаётся в консоли.
   */
  Client.prototype.probe = function () {
    var self = this;
    return fetch(this.endpoint + '/health', {
      credentials: 'same-origin',
      headers: { 'X-Site-Key': this.siteKey }
    })
      .then(function (r) { return r.json(); })
      .then(function (body) {
        if (body.protocolVersion !== self.protocolVersion) {
          throw new Error('Версия протокола пакета и рантайма не совпадает');
        }
        if (body.ready === false) {
          throw new Error('Рантайм не настроен: нет siteKey');
        }
        return true;
      });
  };

  /* --- корзина ------------------------------------------------------ */

  function renderCart(host, cart, onQty) {
    var list = host.querySelector('.rt-cart__items');
    var total = host.querySelector('.rt-cart__total-value');
    if (!list || !total) return;
    list.textContent = '';

    if (!cart.items.length) {
      list.appendChild(el('li', 'rt-cart__empty', MESSAGES.empty));
    }
    cart.items.forEach(function (item) {
      var row = el('li', 'rt-cart__row');
      row.appendChild(el('span', 'rt-cart__name', item.name));
      row.appendChild(el('span', 'rt-cart__price', money(item.price * item.qty)));

      var controls = el('span', 'rt-cart__qty');
      var minus = el('button', 'rt-btn rt-btn--ghost', '−');
      minus.type = 'button';
      minus.setAttribute('aria-label', 'Убрать одну позицию: ' + item.name);
      minus.onclick = function () { onQty(item, item.qty - 1); };
      controls.appendChild(minus);
      controls.appendChild(el('span', 'rt-cart__count', item.qty));
      var plus = el('button', 'rt-btn rt-btn--ghost', '+');
      plus.type = 'button';
      plus.setAttribute('aria-label', 'Добавить: ' + item.name);
      plus.onclick = function () { onQty(item, item.qty + 1); };
      controls.appendChild(plus);
      row.appendChild(controls);
      list.appendChild(row);
    });
    total.textContent = money(cart.total);
  }

  /* --- оформление --------------------------------------------------- */

  function renderCheckout(host, onSubmit) {
    var form = host.querySelector('.rt-form');
    if (!form) return;
    var hint = form.querySelector('.rt-note');
    var button = form.querySelector('button[type="submit"]');
    var consent = form.querySelector('input[name="consent"]');

    form.onsubmit = function (event) {
      event.preventDefault();
      if (hint) hint.textContent = '';
      if (!consent.checked) {
        if (hint) hint.textContent = MESSAGES.required;
        return;
      }
      button.disabled = true;
      onSubmit(
        {
          name: form.querySelector('input[name="name"]').value,
          phone: form.querySelector('input[name="phone"]').value,
          comment: form.querySelector('textarea[name="comment"]').value,
          consent: true
        },
        function (text, isError) {
          button.disabled = false;
          if (hint) {
            hint.textContent = text;
            hint.className = 'rt-note' + (isError ? ' rt-note--error' : '');
          }
        }
      );
    };
  }

  /* --- поиск -------------------------------------------------------- */

  function renderSearch(host, onSearch) {
    var form = host.querySelector('.rt-search');
    if (!form) return;
    var input = form.querySelector('input[name="q"]');
    var results = form.querySelector('.rt-search__results');

    function run() {
      results.textContent = '';
      onSearch(input.value, results);
    }

    form.onsubmit = function (event) {
      event.preventDefault();
      run();
    };
    // Пустой запрос сразу показывает начало каталога: иначе человек
    // не поймёт, работает ли поиск.
    run();
  }

  /* --- подключение модулей ------------------------------------------ */

  function mountCart(host, client, state) {
    function refresh() {
      return client.request('/cart').then(function (body) {
        state.cart = body.cart;
        renderCart(host, body.cart, function (item, qty) {
          client
            .request('/cart', {
              method: 'POST',
              // Отправляется разница, а не итоговое количество:
              // сервер считает прибавкой (docs/RUNTIME.md). Два блока
              // корзины на одной странице не должны затирать друг друга.
              body: { itemId: item.id, qty: qty - item.qty }
            })
            .then(refresh)
            .catch(function (err) {
              note(host, MESSAGES.changed + message(err));
            });
        });
      });
    }
    state.cartViews.push(refresh);
    refresh().catch(function () {
      // Заглушка уже заменена, но корзина не пришла: блок остаётся
      // пустым с пометкой, а не «рабочей корзиной», которая молчит.
      note(host, message(null));
    });
  }

  function mountCheckout(host, client, state) {
    renderCheckout(host, function (payload, reply) {
      client
        .request('/checkout', { method: 'POST', body: payload })
        .then(function (body) {
          reply(
            'Заказ №' + body.order.id + ' принят. Сумма: ' + money(body.order.total),
            false
          );
          state.cart = { items: [], total: 0, count: 0 };
          // Корзина на странице должна очиститься сразу: заказ уже
          // принят, и оставшиеся позиции вводили бы в заблуждение.
          state.cartViews.forEach(function (view) { view(); });
        })
        .catch(function (err) { reply(message(err), true); });
    });
  }

  function mountSearch(host, client) {
    renderSearch(host, function (query, results) {
      client
        .request('/search?q=' + encodeURIComponent(query))
        .then(function (body) {
          results.textContent = '';
          if (!body.items.length) {
            results.appendChild(el('li', 'rt-search__empty', 'Ничего не найдено'));
            return;
          }
          body.items.forEach(function (item) {
            var row = el('li', 'rt-search__row');
            row.appendChild(el('span', null, item.name));
            row.appendChild(el('span', 'rt-search__price', money(item.price)));
            results.appendChild(row);
          });
        })
        .catch(function (err) {
          results.textContent = '';
          results.appendChild(el('li', 'rt-search__empty', message(err)));
        });
    });
  }

  /* --- добавление в корзину из карточек ---------------------------- */

  /*
   * Обработчик один на страницу, а не по одному на кнопку: кнопок
   * может быть двадцать, и двадцать слушателей сделали бы то же
   * самое, что один на контейнере.
   */
  function bindAddButtons(client, state) {
    document.addEventListener('click', function (event) {
      var button = event.target.closest ? event.target.closest('[data-rt-add]') : null;
      if (!button) return;
      event.preventDefault();
      var itemId = button.getAttribute('data-rt-add');
      client
        .request('/cart', {
          method: 'POST',
          body: { itemId: itemId, qty: 1 }
        })
        .then(function () {
          button.classList.add('is-added');
          button.setAttribute('aria-live', 'polite');
          state.cartViews.forEach(function (view) { view(); });
        })
        .catch(function (err) {
          window.alert(message(err, 'Товар не добавлен'));
        });
    });
  }

  function start(config) {
    if (!config || !config.endpoint || !config.siteKey) return;

    var client = new Client(config);
    client.probe().then(
      function () {
        var state = { cart: { items: [], total: 0, count: 0 }, cartViews: [] };
        var hosts = document.querySelectorAll('[data-runtime]');
        var mounted = 0;

        Array.prototype.forEach.call(hosts, function (host) {
          var kind = host.getAttribute('data-runtime');
          if (kind === 'cart') mountCart(host, client, state);
          else if (kind === 'checkout') mountCheckout(host, client, state);
          else if (kind === 'search') mountSearch(host, client);
          else return;

          mounted += 1;
          // Заглушка убирается только после успешной проверки: до
          // этого момента её текст — единственное честное объяснение.
          var placeholder = host.querySelector('.rt-placeholder');
          if (placeholder) placeholder.hidden = true;
          var body = host.querySelector('.rt-' + (kind === 'checkout' ? 'form' : kind));
          if (body) body.hidden = false;
        });

        if (mounted && state.cartViews.length) bindAddButtons(client, state);
      },
      function (err) {
        // Рантайм настроен неверно или несовместим: заглушки остаются,
        // причина попадает в консоль — иначе её не узнать.
        if (window.console && console.warn) {
          console.warn('AuraBuilder runtime:', err.message);
        }
      }
    );
  }

  function boot() {
    fetch(CONFIG_URL, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(start)
      .catch(function () {
        // runtime.json нет — рантайм не подключён, и это не ошибка.
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
