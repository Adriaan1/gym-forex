import collections
import numpy
import gym
import math
from collections import deque
from numpy import genfromtxt
from gym import utils
from gym import spaces


class ForexEnv(gym.Env):
    """
    This environment simulates a Forex trading account with only one open order 
    at any time.
    
    __init__ parameters:
    
    capital: An initial_capital is loaded in the simulated account as equity.
    sl,tp:   The values for stop-loss and take-profit.
    max_volume: maximum volume of orders as percentage of equity. (def:0.1)
    max_order_time: maximum order time.
    num_ticks: number of lastest ticks to be used as obs. (def:2)
    csv_f:   A path to a CSV file containing the timeseries.
    symbol_num: The number of symbos in the timeseries.
    """
    metadata = {'render.modes': ['human']}

    def __init__(self, dataset="/home/harveybc/gym-forex/datasets/ts_3m.CSV"):
        metadata = {'render.modes': ['human', 'ansi']}
        # initialize initial capital
        capital = 10000
        min_sl = 100
        min_tp = 100
        max_sl = 2000
        max_tp = 1000
        leverage = 100
        # Number of past ticks per feature to be used as observations (1440min=1day, 10080=1Week, 43200=1month, )
        # TODO: Colocar como parámetro
        self.obs_ticks = 48 # best 48@ 700k
        num_symbols = 1
        # TODO: Dejar como params
        self.debug = 0  # Show debug msgs
        #csv_f = 'C:\\Users\\HarveyD\\Anaconda3\\Lib\\site-packages\\gym\\envs\\forex\\ts_4y.CSV'
        csv_f = dataset
        self.initial_capital = capital
        self.equity = capital
        self.balance = capital
        self.balance_ant=capital
        # for equity variation calculus
        self.equity_ant = capital
        # order status: -1=sell, 1=buy, 00=nop
        self.order_status = 0
        self.order_profit = 0.0
        # bonus_type selecciona si usar blance(0)o equity (1) en el cálculo del reward
        self.bonus_type=1
        # symbor of active order (from symbol list)
        self.order_symbol = 0
        # initialize reward value
        self.reward = 0
        # Min / Max SL / TP, Min / Max (Default 1000?) in pips
        self.min_sl = min_sl
        self.min_tp = min_tp
        self.max_sl = max_sl
        self.max_tp = max_tp
        self.pip_cost = 0.00001
        # margin acumulativo = open_price*volume*100000/leverage TODO: Hacer uno para cada orden y recalcular total
        self.margin = 0.0
        # Minimum order time in ticks
        self.min_order_time = 1
        # Order Volume relative to Equity
        self.rel_volume = 0.2
        # spread calculus: 0=from last csv column in pips, 1=lineal from volatility, 2=quadratic, 3=exponential
        self.spread_funct = 0
        # using spread=20 sinse its above the average plus the stddev in alpari but on
        self.spread = 20
        # Leverage (Default 100)
        self.leverage = leverage
        # num_symbols
        self.num_symbols = 1
        # initialize tick counter
        self.tick_count = 0

        # flag para representacion de observaciones 0=valores raw, 1=return
        self.use_return = 0
        # load csv file, The file must contain 16 cols: the 0 = HighBid, 1 = Low, 2 = Close, 3 = NextOpen, 4 = v, 5 = MoY, 6 = DoM, 7 = DoW, 8 = HoD, 9 = MoH, ..<6 indicators>
        self.my_data = genfromtxt(csv_f, delimiter=',')
        # initialize number of ticks from from CSV
        self.num_ticks = len(self.my_data)
        # initialize number of columns from the CSV
        self.num_columns = len(self.my_data[0])
        # Generate pre-processing inputs - TODO(0=no,1=FFT_maxamp,2=Poincare for 1/f(FFT_max_amp),3=FFT_2ndamp,4=Poincare for 3),etc...
        self.preprocessing = 0
        # Select the column from which pre-processing observations will be generated
        self.preprocessing_column = 0
        # Normalization method=0 deja los datos iguales, 1=normaliza, 2= estandariza, 3= estandariza y trunca a rango -1,1
        self.norm_method = 1
        # Initialize arrays for normalization and standarization (min,max, average, stddev)
        self.max = self.num_columns * [-999999.0]
        self.min = self.num_columns * [999999.0]
        self.promedio = self.num_columns * [0.0]
        self.stddev = self.num_columns * [0.0]
        if self.norm_method > 0:
            for i in range(0, self.num_ticks - 1):
                # para cada columna
                for j in range(0, self.num_columns - 1):
                    # actualiza max y min
                    if self.my_data[i, j] > self.max[j]:
                        self.max[j] = self.my_data[i, j]
                    if self.my_data[i, j] < self.min[j]:
                        self.min[j] = self.my_data[i, j]
                        # incrementa acumulador
                        self.promedio[j] = self.promedio[j] + self.my_data[i, j]
            self.promedio = [x / self.num_ticks for x in self.promedio]
        if self.norm_method > 1:
            for i in range(0, self.num_ticks - 1):
                # para cada columna
                for j in range(0, self.num_columns - 1):
                    # calcula cuadrados de distancia a promedio
                    self.stddev[j] = self.stddev[j] + (self.my_data[i, j] - self.promedio) ** 2
        # calcula promedio y stddev
        self.stddev = [(x / self.num_ticks) ** 0.5 for x in self.stddev]
        # reward function 0=equity variation, 1=Table
        self.reward_function = 0
        # IF REWARD TABLE IS USED, SET THE NUMBER OR STATE COLS TO 18?
        if (self.reward_function == 0):
            # matrix for the state(order status, equity variation, reward and statistics (from reward table))
            self.state_columns = 3
        else:
            self.state_columns = 18
        # Serial data - to - parallel observation matrix and state matrix
        self.obs_matrix = self.num_columns * [deque(self.obs_ticks * [0.0], self.obs_ticks)]
        self.state = self.state_columns * [deque(self.obs_ticks * [0.0], self.obs_ticks)]

        # action space = nop,buy,sell
        self.action_space = spaces.Discrete(3)
        # observation_space=(16 columns + 3 state variables)* obs_ticks, shape=(width,height, channels?)
        self.observation_space = spaces.Box(low=-1.0, high=1.0, shape=(self.obs_ticks, 1, 19))
        self.order_time = 0
        # TODO; Quitar cuando se controle SL Y TP
        self.sl = self.max_sl
        self.tp = self.max_tp

    """
    _step parameters:
    
    action from action set:
        discrete action 0: 0=nop,1=buy,2=sell. 
#TODO: PROBAR CON 4 ACCIONES: 0=NOP,1=BUY, -1=SELL, CLOSE
        discrete action 0 parameter: symbol
        (optional) continuous action 0 parameter: percent_tp, percent_sl, percent_of_max_volume
    
    _step return values: 
    
    observation: A concatenation of num_ticks vectors for the lastest: 
                 vector of values from timeseries, equity and its variation, 
                 order_status( 0 nop, -1=closed,1=opened),time_opened (normalized with
                 max_order_time), order_profit and its variation, order_drawdown
                 /order_volume_pips,  Performance?=ver archivo Reward2.xlsx tab Long-Term

    reward: Ver archivo Reward2.xlsx tab Short-Term
            TODO: Perf_total=Perf*reward_acum?
    episode_over: Imprime statistics

    """

    def step(self, action):
        # read time_variables from CSV. Format: 0 = HighBid, 1 = Low, 2 = Close, 3 = NextOpen, 4 = v, 5 = MoY, 6 = DoM, 7 = DoW, 8 = HoD, 9 = MoH, ..<num_columns>
        High = self.my_data[self.tick_count, 0]
        Low = self.my_data[self.tick_count, 1]
        Close = self.my_data[self.tick_count, 2]
        DoW = self.my_data[self.tick_count, 7]
        HoD = self.my_data[self.tick_count, 8]
        MoY = self.my_data[self.tick_count, 5]
        DoM = self.my_data[self.tick_count, 6]
        MoH = self.my_data[self.tick_count, 9]
        # Elevate spread  at 0 hours and if its weekend (DoW<=2 and Hour < 2)or(DoW>=5 and Hour > 23)
        if (DoW < 1 or DoW > 5) or (HoD < 2 and HoD > 23):
            spread = self.pip_cost * 60
        else:
            spread = self.pip_cost * 20

        # Calculates profit
        self.profit_pips = 0
        self.real_profit = 0
        if self.order_status == 1:
            # Low_Bid - order_open min and real profit pips (1 lot = 100000 units of currency)
            self.profit_pips = ((Low - self.open_price) / self.pip_cost)
            self.real_profit = self.profit_pips * self.pip_cost * self.order_volume * 100000
        if self.order_status == -1:
            # Order_open - High_Ask (High+spread)
            self.profit_pips = ((self.open_price - (High + spread)) / self.pip_cost)
            self.real_profit = self.profit_pips * self.pip_cost * self.order_volume * 100000
        # Calculates equity
        self.equity = self.balance + self.real_profit
        # Verify if Margin Call
        episode_over = bool(0)
        if self.equity < self.margin:
            # Close order
            self.order_status = 0
            # Calculate new balance
            self.balance = 0.0
            # Calculate new balance
            self.equity = 0.0
            # reset margin
            self.margin = 0.0
            # Set closing cause 1 = Margin call
            self.c_c = 1
            # End episode
            episode_over = bool(1)
            # TODO: ADICIONAR CONTROLES PARA SL Y TP ENTRE MAX_SL Y TP
            # print transaction: Num,DateTime,Type,Size,Price,SL,TP,Profit,Balance
            print(self.tick_count, ',margin_call, b', self.balance, ',d', MoY, '-', DoM, ' ', HoD, ':', MoH)
        if (episode_over==False):
            # Verify if close by SL
            if self.profit_pips <= (-1 * self.sl):
                # Close order
                self.order_status = 0
                # Calculate new balance
                self.balance = self.equity
                # resets margin
                self.margin = 0.0
                # print transaction: Num,DateTime,Type,Size,Price,SL,TP,Profit,Balance
                if self.debug == 1:
                    print(self.tick_count, ',stop_loss, o', self.open_price, ',p', self.profit_pips, ',v',
                          self.order_volume, ',b', self.balance, ',d', MoY, '-', DoM, ' ', HoD, ':', MoH)
                # Set closing cause 2 = sl
                self.c_c = 2
            # Verify if close by TP
            if self.profit_pips >= self.tp:
                # Close order
                self.order_status = 0
                # Calculate new balance
                self.balance = self.equity
                # reset margin
                self.margin = 0.0
                # print transaction: Num,DateTime,Type,Size,Price,SL,TP,Profit,Balance
                if self.debug == 1:
                    print(self.tick_count, ',take_profit, o', self.open_price, ',p', self.profit_pips, ',v',
                          self.order_volume, ',b', self.balance, ',d', MoY, '-', DoM, ' ', HoD, ':', MoH)
                # Set closing cause 3 = tp
                self.c_c = 3
            # TODO: Hacer opcion realista de ordenes que se ABREN Y CIERRAN solo si durante el siguiente minuto
            #       el precio de la orden(close) no es high o low del siguiente candle.
            # Executes action, NewState = Previous * TableOfActionsPerState :)
            if (self.order_status == 0 or self.order_status == -1) and action == 1:
                if self.order_status == -1:
                    self.balance = self.equity
                    self.margin = 0
                self.order_status = 1
                # open price = Ask (Close_bid+Spread)
                self.open_price = Close + spread
                # order_volume = lo que alcanza con rel_volume de equity
                self.order_volume = self.equity * self.rel_volume * self.leverage / 100000
                # redondear a volumenes minimos de 0.01
                self.order_volume = math.trunc(self.order_volume * 100) / 100.0
                # si volume menos del mínimo, hace volumen= mínimo TODO: QUITAR? CUANDO SE CALCULE VOLUME
                if self.order_volume <= 0.01:
                    # close existing order
                    self.order_volume = 0.01
                    self.margin = 0
                # set the new margin
                self.margin = self.margin + (self.order_volume * 100000 / self.leverage)
                # TODO: Colocar accion para tamano de lote con rel_volume como maximo al abrir una orden
                self.order_time = self.tick_count
                # print transaction: Num,DateTime,Type,Size,Price,SL,TP,margin,equity
                if self.debug == 1:
                    print(self.tick_count, ',buy, o', self.open_price, ',v', self.order_volume, ',m', self.margin, ',e',
                          self.equity, ',b', self.balance, ',d', MoY, '-', DoM, ' ', HoD, ':', MoH)
            if (self.order_status == 0 or self.order_status == 1) and action == 2:
                if self.order_status == 1:
                    # close existing order
                    self.balance = self.equity
                self.order_status = -1
                # open_price = Bid
                self.open_price = Close
                # order_volume = lo que alcanza con rel_volume de equity
                self.order_volume = self.equity * self.rel_volume * self.leverage / 100000
                # redondear a volumenes minimos de 0.01
                self.order_volume = math.trunc(self.order_volume * 100) / 100.0
                # set the new margin
                self.margin = self.margin + (self.order_volume * 100000 / self.leverage)
                self.order_time = self.tick_count
                # TODO: Hacer version con controles para abrir y cerrar para buy y sell independientes,comparar
                # print transaction: Num,DateTime,Type,Size,Price,SL,TP,Profit,Balance
                if self.debug == 1:
                    print(self.tick_count, ',sell, o', self.open_price, ',v', self.order_volume, ',m', self.margin, ',e',
                          self.equity, ',b', self.balance, ',d', MoY, '-', DoM, ' ', HoD, ':', MoH)
                    # TODO: Verificar si ha pasado el min_order_time desde que se abrieron antes de cerrar
            if ((self.tick_count - self.order_time) > self.min_order_time):
                if self.order_status == 1 and action == 1:
                    self.order_status = 0
                    self.balance = self.equity
                    self.margin = 0
                    # print transaction: Num,DateTime,Type,Size,Price,SL,TP,Profit,Balance
                    if self.debug == 1:
                        print(self.tick_count, ',close_buy, o', self.open_price, ',p', self.profit_pips, ',v',
                              self.order_volume, ',e', self.equity, ',b', self.balance, ',d', MoY, '-', DoM, ' ', HoD, ':',
                              MoH)
                if self.order_status == -1 and action == 2:
                    self.order_status = 0
                    self.balance = self.equity
                    self.margin = 0
                    # print transaction: Num,DateTime,Type,Size,Price,SL,TP,Profit,Balance
                    if self.debug == 1:
                        print(self.tick_count, ',close_sell, o', self.open_price, ',p', self.profit_pips, ',v',
                              self.order_volume, ',e', self.equity, ',b', self.balance, ',d', MoY, '-', DoM, ' ', HoD, ':',
                              MoH)
        # Calculates reward from RewardFunctionTable
        reward = 0
        # Bonus_type selecciona si usar Balance=0 o Equity=1
        if self.bonus_type == 0:
            equity_increment = self.balance - self.balance_ant
        else:
            equity_increment = self.equity - self.equity_ant
        if self.reward_function == 0:
            # TODO: REWARD FUNCTION:  1=Tabla
            # reward de duración hasta alcanzar total de ticks
            # reward = reward + self.tick_count / (self.num_ticks)
            bonus=((self.tick_count/self.num_ticks)+1)*((self.equity_ant * equity_increment) / (self.initial_capital * self.num_ticks))
            reward = reward + bonus
            if ((self.equity_ant>=(0.5*self.initial_capital)) and (equity_increment>0)):
                reward = reward + bonus
            if ((self.equity_ant >= (0.75 * self.initial_capital)) and (equity_increment > 0)):
                reward = reward + 2*bonus
            if ((self.equity_ant >= self.initial_capital) and (equity_increment > 0)):
                reward = reward + 4*bonus
            if ((self.equity_ant >= (2*self.initial_capital)) and (equity_increment > 0)):
                reward = reward + 8*bonus
            if ((self.equity_ant >= (4 * self.initial_capital)) and (equity_increment > 0)):
                reward = reward + 16*bonus
            if ((self.equity_ant >= (8 * self.initial_capital)) and (equity_increment > 0)):
                reward = reward + 32*bonus
            if ((self.equity_ant >= (16 * self.initial_capital)) and (equity_increment > 0)):
                reward = reward + 64*bonus

                    # if self.order_status==0:
                # TODO: penalizar reward con el cuadrado del tiempo que lleva sin orden * -0.01
                # para evitar que sin acciones se obtenga ganancia 0 al final (deseado: -2, entonces variación=-2/num_ticks)
                # TODO: Auto-calcular reward descontado por inectividad como función del total de ticks?
                # reward=reward-0.00001 #Best result con 0.0001 (148k)

        # Push values from timeseries into state
        # 0 = HighBid, 1 = Low, 2 = Close, 3 = NextOpen, 4 = v, 5 = MoY, 6 = DoM, 7 = DoW, 8 = HoD, 9 = MoH, ..<num_columns>
        for i in range(0, self.num_columns - 1):
            # normalizes between -1,1
            obs_normalized = (2.0 * (self.my_data[self.tick_count, i] - self.min[i]) / (self.max[i] - self.min[i])) - 1.0
            self.obs_matrix[i].append(obs_normalized)
        # matrix for the state(order status, equity variation, reward and statistics (from reward table))
        # TODO: order time opened?
        obs_normalized = self.order_status
        self.state[0].append(obs_normalized)
        # return of equity normalized? TODO: Proper normalization. with estimation of max and min eq return?
        self.state[1].append((self.equity - self.equity_ant) / self.equity_ant)
        # normalized profit
        self.state[2].append((self.equity - self.initial_capital) / self.initial_capital)
        # merge obs_matrix and state in ob
        ob = numpy.concatenate([self.obs_matrix, self.state])
        # increment tick counter
        self.tick_count = self.tick_count + 1
        # update equity_Ant
        self.equity_ant = self.equity
        self.balance_ant=self.balance
        # Episode over es TRUE cuando se termina el juego, es decir cuando tick_count=self.num_ticks
        if self.tick_count >= (self.num_ticks - 1):
            episode_over = bool(1)
            print('episode_over, Balance =', self.equity, ',  Performance =', self.balance / self.initial_capital,
                  ', Time=', self.tick_count)
            # self._reset()
            # self.__init__()
            # TODO: IMPRIMIR ESTADiSTICAS DE METATRADER
        # end of step function.
        return ob, reward, episode_over, self.balance, self.tick_count, {}

    """
    _reset: coloca todas las variables en valores iniciales
    """

    def reset(self):
        self.tick_count = 0
        self.equity = self.initial_capital
        self.balance = self.equity
        self.balance_ant = self.balance
        self.equity_ant = self.equity
        self.obs_matrix = self.num_columns * [deque(self.obs_ticks * [0.0], self.obs_ticks)]
        self.state = self.state_columns * [deque(self.obs_ticks * [0.0], self.obs_ticks)]
        self.order_status = 0
        self.reward = 0
        self.order_profit = 0.0
        self.margin = 0.0
        # Serial data - to - parallel observation matrix and state matrix
        self.obs_matrix = self.num_columns * [deque(self.obs_ticks * [0.0], self.obs_ticks)]
        self.state = self.state_columns * [deque(self.obs_ticks * [0.0], self.obs_ticks)]
        ob = numpy.concatenate([self.obs_matrix, self.state])
        self.__init__()
        return ob

    """
    _render: muestra performance de ultima orden, performance general y OPCIONALMENTE actualiza un grafico del equity
     con tabla de orders y el balance por tick cuando se termine la simulacion (episode_over?) similar a
    https://www.metatrader4.com/en/trading-platform/help/autotrading/tester/tester_results
    def _render(self, mode='human', close=False):
        print 'Eq=', self.equity
    """

    def render(self, mode='human', close=False):
        if mode == 'human':
            return self.equity
        else:
            super(ForexEnv, self).render(mode=mode)  # just raise an exception
