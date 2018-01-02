import time
import json
import sqlite3
import numpy
import talib
import poloniex
from datetime import datetime

API_KEY = 'T22UNIMI-RIPLNU08-2T85OQY0-6JS7Q4PA'
SECRET_KEY = 'b604caf8b44e24c7d2ccc770c6ec8f5965e3fe47e8635616082056c0d4dbfeb30070a0c0ef0107627006d25a2e08200920bee53bdd68ffcbd187c007cff30cb3'

MARKETS = [
    'BTC_ETH',
    'BTC_BCH',
    'BTC_ZEC',
    'BTC_CVC',
    'BTC_XEM',
    'BTC_VTC'
]

CAN_SPEND = 0.0002
MARKUP = 0.001

STOCK_FEE = 0.0025

ORDER_LIFE_TIME = 5

USE_MACD = True

BEAR_PERC = 70
BULL_PERC = 95

USE_LOG = False

numpy.seterr(all='ignore')

conn = sqlite3.connect('local.db')
cursor = conn.cursor()

curr_market = None

poloniex_api = poloniex.Poloniex(API_KEY, SECRET_KEY)


class ScriptError(Exception):
    pass


def get_ticks(market):
    chart_data = {}

    data = poloniex_api.returnChartData(market, 1800)

    for item in data:
        if not item['date'] in chart_data:
            chart_data[item['date']] = {
                'open': float(item['open']),
                'close': float(item['close']),
                'high': float(item['high']),
                'low': float(item['low'])
            }

    res = poloniex_api.marketTradeHist(market)
    for trade in reversed(res):
        try:
            dt_obj = datetime.strptime(trade['date'], '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            dt_obj = datetime.strptime(trade['date'], '%Y-%m-%d %H:%M:%S')
        ts = int((time.mktime(dt_obj.timetuple()) / 1800)) * 1800  # округляем до 5 минут
        if not ts in chart_data:
            chart_data[ts] = {'open': 0, 'close': 0, 'high': 0, 'low': 0}

        chart_data[ts]['close'] = float(trade['rate'])

        if not chart_data[ts]['open']:
            chart_data[ts]['open'] = float(trade['rate'])

        if not chart_data[ts]['high'] or chart_data[ts]['high'] < float(trade['rate']):
            chart_data[ts]['high'] = float(trade['rate'])

        if not chart_data[ts]['low'] or chart_data[ts]['low'] > float(trade['rate']):
            chart_data[ts]['low'] = float(trade['rate'])

    return chart_data


def get_macd_advice(chart_data):
    macd, macdsignal, macdhist = talib.MACD(numpy.asarray([chart_data[item]['close'] for item in sorted(chart_data)]),
                                            fastperiod=12, slowperiod=26, signalperiod=9)
    idx = numpy.argwhere(numpy.diff(numpy.sign(macd - macdsignal)) != 0).reshape(-1) + 0

    trand = 'BULL' if macd[-1] > macdsignal[-1] else 'BEAR'

    max_v = 0

    activity_time = False
    growing = False

    for offset, elem in enumerate(macdhist):

        growing = False

        curr_v = macd[offset] - macdsignal[offset]
        if abs(curr_v) > abs(max_v):
            max_v = curr_v
        perc = curr_v / max_v

        if ((macd[offset] > macdsignal[offset] and perc * 100 > BULL_PERC)  # восходящий тренд
                or (
                        macd[offset] < macdsignal[offset] and perc * 100 < (100 - BEAR_PERC)
                )
        ):
            activity_time = True

            growing = True

        if offset in idx and not numpy.isnan(elem):
            max_v = curr_v = 0

    return ({'trand': trand, 'growing': growing})


# Выводит всякую информацию на экран, самое важное скидывает в Файл log.txt
def log(*args):
    if USE_LOG:
        l = open("./log.txt", 'a', encoding='utf-8')
        print(datetime.now(), *args, file=l)
        l.close()
    print(datetime.now(), *args)


def create_buy(market):
    global USE_LOG
    USE_LOG = True

    log(market, 'Создаем ордер на покупку')
    log(market, 'Получаем текущие курсы')
    ticker_data = poloniex_api.returnTicker()[market]
    current_rate = float(ticker_data['lowestAsk'])
    can_buy = CAN_SPEND / current_rate

    pair = market.split('_')
    log(market, """
        Текущая цена - %0.8f
        На сумму %0.8f %s можно купить %0.8f %s
        Создаю ордер на покупку
        """ % (current_rate, CAN_SPEND, pair[0], can_buy, pair[1])
        )
    try:
        order_res = poloniex_api.buy(market, current_rate, can_buy)
    except poloniex.PoloniexError:
        btc_balance = poloniex_api.returnBalances()['BTC']
        log(market, 'Не хватило денег на покупку, текущий баланс: %s' % btc_balance)
        USE_LOG = False
        return

    if order_res['orderNumber']:
        cursor.execute(
            """
              INSERT INTO orders(
                  order_id,
                  order_type,
                  order_pair,
                  order_created,
                  order_price,
                  order_amount,
                  order_spent
              ) Values (
                :order_id,
                'buy',
                :order_pair,
                datetime(),
                :order_price,
                :order_amount,
                :order_spent
              )
            """, {
                'order_id': order_res['orderNumber'],
                'order_pair': market,
                'order_price': current_rate,
                'order_amount': can_buy,
                'order_spent': CAN_SPEND

            })
        conn.commit()
        log("Создан ордер на покупку %s" % order_res['orderNumber'])
    else:
        log(market, """
            Не удалось создать ордер: %s
        """ % order_res['message'])
    USE_LOG = False


def create_sell(from_order, market):
    global USE_LOG
    USE_LOG = True

    pair = market.split('_')
    buy_order_q = """
        SELECT order_spent, order_amount FROM orders WHERE order_id='%s'
    """ % from_order
    cursor.execute(buy_order_q)
    order_spent, order_amount = cursor.fetchone()
    new_rate = (order_spent + order_spent * MARKUP) / order_amount

    new_rate_fee = new_rate + (new_rate * STOCK_FEE) / (1 - STOCK_FEE)

    ticker_data = poloniex_api.returnTicker()[market]

    current_rate = float(ticker_data['highestBid'])

    choosen_rate = current_rate if current_rate > new_rate_fee else new_rate_fee

    log(market, """
        Итого на этот ордер было потрачено %0.8f %s, получено %0.8f %s
        Что бы выйти в плюс, необходимо продать купленную валюту по курсу %0.8f
        Тогда, после вычета комиссии %0.4f останется сумма %0.8f %s
        Итоговая прибыль составит %0.8f %s
        Текущий курс продажи %0.8f
        Создаю ордер на продажу по курсу %0.8f
    """
        % (
            order_spent, pair[0], order_amount, pair[1],
            new_rate_fee,
            STOCK_FEE, (new_rate_fee * order_amount - new_rate_fee * order_amount * STOCK_FEE), pair[0],
            (new_rate_fee * order_amount - new_rate_fee * order_amount * STOCK_FEE) - order_spent, pair[0],
            current_rate,
            choosen_rate,
        )
        )

    order_res = poloniex_api.sell(market, choosen_rate, order_amount)

    if order_res['orderNumber']:
        cursor.execute(
            """
              INSERT INTO orders(
                  order_id,
                  order_type,
                  order_pair,
                  order_created,
                  order_price,
                  order_amount,
                  from_order_id
              ) Values (
                :order_id,
                'sell',
                :order_pair,
                datetime(),
                :order_price,
                :order_amount,
                :from_order_id
              )
            """, {
                'order_id': order_res['orderNumber'],
                'order_pair': market,
                'order_price': choosen_rate,
                'order_amount': order_amount,
                'from_order_id': from_order

            })
        conn.commit()
        log(market, "Создан ордер на продажу %s" % order_res['orderNumber'])
    USE_LOG = False


orders_q = """
  create table if not exists
    orders (
      order_id TEXT,
      order_type TEXT,
      order_pair TEXT,
      order_created DATETIME,
      order_filled DATETIME,
      order_cancelled DATETIME,
      from_order_id TEXT,
      order_price REAL,
      order_amount REAL,
      order_spent REAL
    );
"""
cursor.execute(orders_q)

while True:

    for market in MARKETS:
        log(market, "Получаем все неисполненные ордера по БД")
        orders_q = """
                       SELECT
                         o.order_id,
                         o.order_type,
                         o.order_price,
                         o.order_amount,
                         o.order_filled,
                         o.order_created
                       FROM
                         orders o
                       WHERE
                            o.order_pair='%s'
                            AND (
                                    (o.order_type = 'buy' and o.order_filled IS NULL)
                                    OR
                                    (o.order_type = 'buy' AND order_filled IS NOT NULL AND NOT EXISTS (
                                        SELECT 1 FROM orders o2 WHERE o2.from_order_id = o.order_id
                                        )
                                    )
                                    OR (
                                        o.order_type = 'sell' and o.order_filled IS NULL
                                    )
                                )
                            AND o.order_cancelled IS NULL
                   """ % market

        orders_info = {}
        for row in cursor.execute(orders_q):
            orders_info[str(row[0])] = {'order_id': row[0], 'order_type': row[1], 'order_price': row[2],
                                        'order_amount': row[3], 'order_filled': row[4], 'order_created': row[5]
                                        }

        if orders_info:
            log(market, "Получены неисполненные ордера из БД", orders_info)
            for order in orders_info:
                if not orders_info[order]['order_filled']:
                    log(market, "Проверяем состояние ордера %s" % order)
                    try:
                        order_info = poloniex_api.returnOrderTrades(orders_info[order]['order_id'])
                        log(market, 'Ордер %s уже выполнен!' % order)

                        order_sum_info = {
                            'rate': 0,
                            'amount': 0,
                            'fee': 0
                        }

                        i = 1

                        for order_trade in order_info:
                            order_sum_info['rate'] += float(order_trade['rate'])
                            order_sum_info['amount'] += float(order_trade['amount'])
                            order_sum_info['fee'] += float(order_trade['fee'])
                            i += 1

                        order_sum_info['rate'] /= i
                        order_sum_info['fee'] /= i

                        cursor.execute(
                            """
                              UPDATE orders
                              SET
                                order_filled=datetime(),
                                order_price=:order_price,
                                order_amount=:order_amount,
                                order_spent=order_spent + :fee * order_spent
                              WHERE
                                order_id = :order_id

                            """, {
                                'order_id': order,
                                'order_price': order_sum_info['rate'],
                                'order_amount': order_sum_info['amount'],
                                'fee': float(order_sum_info['fee'])
                            }
                        )
                        conn.commit()
                        log(market, "Ордер %s помечен выполненным в БД" % order)
                        orders_info[order]['order_filled'] = datetime.now()
                    except poloniex.PoloniexError as e:
                        log(market, "Ордер %s еще не выполнен потому что %s" % (order, e))

            for order in orders_info:
                if orders_info[order]['order_type'] == 'buy':
                    if orders_info[order]['order_filled']:  # если ордер на покупку был выполнен

                        if USE_MACD:
                            macd_advice = get_macd_advice(
                                chart_data=get_ticks(market))  # проверяем, можно ли создать sell
                            if macd_advice['trand'] == 'BEAR' or (
                                    macd_advice['trand'] == 'BULL' and macd_advice['growing']):
                                log(market,
                                    'Для ордера %s не создаем ордер на продажу, т.к. ситуация на рынке неподходящая' % order)
                            else:
                                log(market, "Для выполненного ордера на покупку выставляем ордер на продажу")
                                create_sell(from_order=orders_info[order]['order_id'], market=market)
                        else:  # создаем sell если тенденция рынка позволяет
                            log(market, "Для выполненного ордера на покупку выставляем ордер на продажу")
                            create_sell(from_order=orders_info[order]['order_id'], market=market)
                    else:  # Если buy не был исполнен, и прошло достаточно времени для отмены ордера, отменяем
                        if 'order_canceled' not in orders_info[order] or not orders_info[order]['order_cancelled']:
                            order_time = time.mktime(datetime.strptime(orders_info[order]['order_created'],
                                                                       "%Y-%m-%d %H:%M:%S").timetuple())
                            time_passed = time.time() - order_time

                            if time_passed > ORDER_LIFE_TIME * 60:
                                log('Пора отменять ордер %s' % order)
                                cancel_res = poloniex_api.cancelOrder(order)
                                if cancel_res['success']:
                                    cursor.execute(
                                        """
                                          UPDATE orders
                                          SET
                                            order_cancelled=datetime()
                                          WHERE
                                            order_id = :order_id

                                        """, {
                                            'order_id': order
                                        }
                                    )
                                    conn.commit()
                                    log(market, "Ордер %s помечен отмененным в БД" % order)

                else:  # ордер на продажу
                    if 'order_canceled' not in orders_info[order] or not orders_info[order]['order_cancelled']:
                        order_time = time.mktime(datetime.strptime(orders_info[order]['order_created'],
                                                                   "%Y-%m-%d %H:%M:%S").timetuple())
                        time_passed = time.time() - order_time

                        if time_passed > ORDER_LIFE_TIME * 60:
                            log('Пора отменять ордер %s' % order)
                            cancel_res = poloniex_api.cancelOrder(order)
                            if cancel_res['success']:
                                cursor.execute(
                                    """
                                      UPDATE orders
                                      SET
                                        order_cancelled=datetime()
                                      WHERE
                                        order_id = :order_id

                                    """, {
                                        'order_id': order
                                    }
                                )
                                conn.commit()
                                log(market, "Ордер на продажу %s помечен отмененным в БД" % order)
        else:
            log(market, "Неисполненных ордеров в БД нет, пора ли создать новый?")
            # Проверяем MACD, если рынок в нужном состоянии, выставляем ордер на покупку
            if USE_MACD:
                macd_advice = get_macd_advice(chart_data=get_ticks(market))
                if macd_advice['trand'] == 'BEAR' and macd_advice['growing']:
                    log(market, "Создаем ордер на покупку")
                    create_buy(market=market)
                else:
                    log(market, "Условия рынка не подходят для торговли", macd_advice)
            else:
                log(market, "Создаем ордер на покупку")
                create_buy(market=market)

    time.sleep(1)
