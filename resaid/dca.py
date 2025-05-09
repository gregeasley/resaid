from re import S
import pandas as pd
import numpy as np
import sys
import statsmodels.api as sm
from scipy.signal import argrelextrema
from scipy.optimize import curve_fit, fsolve
from dateutil.relativedelta import *
import time
import math

import warnings
from tqdm import tqdm
warnings.simplefilter("ignore")

class decline_solver():

    def __init__(self, qi=None, qf=None, de=None, dmin=None, b=None, eur=None, t_max=None):

        
        self.qi = qi
        self.qf = qf
        self.de = de
        self.dmin = dmin
        self.b = b
        self.eur = eur
        self.t_max = t_max

        self.l_qf = qf
        self.l_t_max = t_max
        self.delta = 0
        
        self.variables_to_solve = []

        self.l_dca = decline_curve()

    def determine_solve(self):
        # Use match/case to handle different input cases and calculate the missing variables

        match (None, None):
            case (self.qi, self.t_max):
                self.variables_to_solve = ['qi']
                self.qi = self.qf + self.de * self.eur
                self.t_max = 1200
            case (self.qi, self.qf):
                self.variables_to_solve = ['qi']
                self.qi = self.de * self.eur/2
                self.qf = 1
            case (self.qi, self.de):
                self.variables_to_solve = ['qi','de']
                self.qi = self.qf + self.dmin * self.eur
                self.de = (self.qi - self.qf) / self.eur
            case (self.qi, self.eur):
                self.variables_to_solve = ['qi','eur']
                self.qi = self.qf /self.de 
                self.eur = (self.qi - self.qf) / self.de
            case (self.t_max, self.qf):
                self.variables_to_solve = ['qf']
                self.qf = max(self.qi - self.de * self.eur,1)
                self.t_max = 1200
            case (self.t_max, self.de):
                self.variables_to_solve = ['de']
                self.de = (self.qi - self.qf) / self.eur
                self.t_max = 1200
            case (self.t_max, self.eur):
                self.variables_to_solve = ['eur']
                self.t_max = 1200
                self.eur = (self.qi - self.qf) / self.de
            case (self.qf, self.de):
                self.variables_to_solve = ['de']
                self.de = (self.qi) / self.eur
                self.qf = 1
            case (self.qf, self.eur):
                self.variables_to_solve = ['eur']
                self.eur = (self.qi) / self.de
                self.qf = 1
            case (self.de, self.eur):
                self.variables_to_solve = ['de','eur']
                self.eur = self.qi*self.t_max
                self.de = (self.qi - self.qf) / self.eur


    def dca_delta(self,vars_to_solve):

        for var_name, var_value in zip(self.variables_to_solve, vars_to_solve):
            setattr(self, var_name, var_value)

        self.l_dca.D_MIN = self.dmin
        t_range = np.array(range(0,int(self.t_max)))

        dca_array = np.array(self.l_dca.arps_decline(t_range,self.qi,self.de,self.b,0))

        


        dca_array = np.where(dca_array>self.qf,dca_array,0)


        self.l_t_max = len(np.where(dca_array > 0)[0])
        if self.l_t_max >0:
            self.l_qf = dca_array[np.where(dca_array > 0)[0][-1]]

        delta = np.sum(dca_array) - self.eur

        self.delta = delta

        return [delta] * len(self.variables_to_solve)
    
    def solve(self):

        self.determine_solve()

        initial_guess = [getattr(self, var) for var in self.variables_to_solve if getattr(self, var) is not None]

        result, infodict, ier, msg = fsolve(self.dca_delta, initial_guess, full_output=True)

        if ier==1:
            warning_flag = 0
        else:
            warning_flag = 1
        

        for var_name, var_value in zip(self.variables_to_solve, result):
            setattr(self, var_name, var_value)

        if 't_max' in self.variables_to_solve or len(self.variables_to_solve)==1:
            self.t_max = self.l_t_max

        if 'qf' in self.variables_to_solve or len(self.variables_to_solve)==1:
            self.qf = self.l_qf
        return self.qi, self.t_max, self.qf, self.de, self.eur, warning_flag, self.delta


class decline_curve:

    def __init__(self):
        #Constants
        self.DAY_NORM = 30.4
        self.GAS_CUTOFF = 3.2 #GOR for classifying well as gas or oil, MSCF/STB
        self.STAT_FILE = sys.stdout
        self.MINOR_TAIL = 6 #Number of months from tail to use for minor phase ratios
        self.SET_LENGTH = 5280 #Length to normalize horizontals to
        self.D_MIN = .08/12 #Minimum monthly decline rate
        self.DEBUG_ON = False
        #Settable 
        self.verbose = True
        self.FILTER_BONFP = .5 #Normally set to .5
        self.DEFAULT_DI  = .8/12
        self.DEFAULT_B = .5
        self.V_DCA_FAILURES = 0
        self.OUTLIER_CORRECTION = True
        self.IQR_LIMIT = 1.5
        self._min_h_b = .99
        self._max_h_b = 2
        
        self._backup_decline = False
        self._dataframe = None
        self._date_col = None
        self._phase_col = None
        self._length_col = None
        self._uid_col = None
        self._dayson_col = None
        self._oil_col = None
        self._gas_col = None
        self._water_col = None
        self._input_monthly = True

        self._force_t0 = False

        #Get only variables
        self._normalized_dataframe = pd.DataFrame()
        self._params_dataframe = pd.DataFrame([])
        self._flowstream_dataframe = None
        self._typecurve = None
        self._oneline = pd.DataFrame()

        self.tc_params = pd.DataFrame()
        self.dca_param_df = []
        

    @property
    def dataframe(self):
        return self._dataframe


    @dataframe.setter
    def dataframe(self,value):
        self._dataframe = value

    @property
    def input_monthly(self):
        return self._input_monthly


    @input_monthly.setter
    def input_monthly(self,value):
        self._input_monthly = value

    @property
    def date_col(self):
        return self._date_col


    @date_col.setter
    def date_col(self,value):
        self._date_col = value

    @property
    def phase_col(self):
        return self._phase_col


    @phase_col.setter
    def phase_col(self,value):
        self._phase_col = value

    @property
    def length_col(self):
        return self._length_col


    @length_col.setter
    def length_col(self,value):
        self._length_col = value

    @property
    def uid_col(self):
        return self._uid_col


    @uid_col.setter
    def uid_col(self,value):
        self._uid_col = value

    @property
    def dayson_col(self):
        return self._dayson_col


    @dayson_col.setter
    def dayson_col(self,value):
        self._dayson_col = value

    @property
    def oil_col(self):
        return self._oil_col


    @oil_col.setter
    def oil_col(self,value):
        self._oil_col = value

    @property
    def gas_col(self):
        return self._gas_col


    @gas_col.setter
    def gas_col(self,value):
        self._gas_col = value

    @property
    def water_col(self):
        return self._water_col


    @water_col.setter
    def water_col(self,value):
        self._water_col = value


    @property
    def backup_decline(self):
        return self._backup_decline


    @backup_decline.setter
    def backup_decline(self,value):
        self._backup_decline = value

    @property
    def min_h_b(self):
        return self._min_h_b


    @min_h_b.setter
    def min_h_b(self,value):
        self._min_h_b= value


    @property
    def max_h_b(self):
        return self._max_h_b


    @max_h_b.setter
    def max_h_b(self,value):
        self._max_h_b= value

    @property
    def params_dataframe(self):
        return self._params_dataframe

    @property
    def flowstream_dataframe(self):
        return self._flowstream_dataframe

    @property
    def oneline_dataframe(self):
        return self._oneline

    @property
    def typecurve(self):
        return self._typecurve

    def month_diff(self, a, b):
        return 12 * (a.dt.year - b.dt.year) + (a.dt.month - b.dt.month)

    def day_diff(self,a,b):
        return (a - b) / np.timedelta64(1, 'D')

    def infill_production(self):
        """
        An error was found where gaps in the historical production would be infilled
        with the wrong P_DATE
        """

    def generate_t_index(self):
        #print(self._date_col, file=self.STAT_FILE, flush=True)
        self._dataframe[self._date_col] = pd.to_datetime(self._dataframe[self._date_col])
        min_by_well = self._dataframe[[self._uid_col,self._date_col]].groupby(by=[self._uid_col]).min().reset_index()
        min_by_well = min_by_well.rename(columns={self._date_col:'MIN_DATE'})
        #print(min_by_well)
        
        self._dataframe = self._dataframe.merge(
            min_by_well, 
            left_on = self._uid_col,
            right_on = self._uid_col,
            suffixes=(None,'_MIN')
        )

        if self._input_monthly:
            self._dataframe['T_INDEX'] = self.month_diff(
                self._dataframe[self._date_col],
                self._dataframe['MIN_DATE']
            )
        else:
            self._dataframe['T_INDEX'] = self.day_diff(
                self._dataframe[self._date_col],
                self._dataframe['MIN_DATE']
            )

        #return 0

    def assign_major(self):
        l_cum = self._normalized_dataframe[['UID','NORMALIZED_OIL','NORMALIZED_GAS']].groupby(by=['UID']).sum().reset_index()
        l_cum['MAJOR'] = np.where(
            l_cum["NORMALIZED_OIL"] >0,
            np.where(
                l_cum["NORMALIZED_GAS"]/l_cum['NORMALIZED_OIL']>self.GAS_CUTOFF,
                'GAS',
                'OIL'
            ),
            "GAS"
        )

        self._normalized_dataframe = self._normalized_dataframe.merge(
            l_cum,
            left_on = "UID",
            right_on = "UID",
            suffixes=(None,'_right')
        )

    def normalize_production(self):

        self._normalized_dataframe['UID'] = self._dataframe[self._uid_col]
        self._normalized_dataframe['T_INDEX'] = self._dataframe['T_INDEX']

        if self._length_col == None:
            self._normalized_dataframe['LENGTH_NORM'] = 1.0
        else:
            self._dataframe[self._length_col] = self._dataframe[self._length_col].fillna(0)

            self._normalized_dataframe['LENGTH_NORM'] = np.where(
                self._dataframe[self._length_col] > 1,
                self._dataframe[self._length_col],
                1
            )

        self._normalized_dataframe['HOLE_DIRECTION'] = np.where(
            self._normalized_dataframe['LENGTH_NORM']> 1,
            "H",
            "V"
        )

        if self._length_col == None:
            self._normalized_dataframe['LENGTH_SET'] = 1.0
        else:
            self._normalized_dataframe['LENGTH_SET'] = np.where(
                self._dataframe[self._length_col] > 1,
                self.SET_LENGTH,
                1.0
            )

        

        if self._dayson_col == None:
            self._normalized_dataframe['DAYSON'] = 30.4
        else:
            self._dataframe[self._dayson_col] = self._dataframe[self._dayson_col].fillna(30.4)

            self._normalized_dataframe['DAYSON'] = np.where(
                self._dataframe[self._dayson_col] > 0,
                self._dataframe[self._dayson_col],
                0
            )

        self._dataframe[self._oil_col] = pd.to_numeric(self._dataframe[self._oil_col], errors='coerce')
        self._dataframe[self._oil_col] = self._dataframe[self._oil_col].fillna(0)

        self._dataframe[self._gas_col] = pd.to_numeric(self._dataframe[self._gas_col], errors='coerce')
        self._dataframe[self._gas_col] = self._dataframe[self._gas_col].fillna(0)

        self._dataframe[self._water_col] = pd.to_numeric(self._dataframe[self._water_col], errors='coerce')
        self._dataframe[self._water_col] = self._dataframe[self._water_col].fillna(0)

        #self._normalized_dataframe.to_csv('outputs/test.csv')

        self._normalized_dataframe['NORMALIZED_OIL'] = (
            self._dataframe[self._oil_col]*
            self.DAY_NORM*
            self._normalized_dataframe['LENGTH_SET'] /
            (self._normalized_dataframe['LENGTH_NORM'] * self._normalized_dataframe['DAYSON'])
        )

        self._normalized_dataframe['NORMALIZED_GAS'] = (
            self._dataframe[self._gas_col]*
            self.DAY_NORM*
            self._normalized_dataframe['LENGTH_SET'] /
            (self._normalized_dataframe['LENGTH_NORM'] * self._normalized_dataframe['DAYSON'])
        )

        self._normalized_dataframe['NORMALIZED_WATER'] = (
            self._dataframe[self._water_col]*
            self.DAY_NORM*
            self._normalized_dataframe['LENGTH_SET'] /
            (self._normalized_dataframe['LENGTH_NORM'] * self._normalized_dataframe['DAYSON'])
        )

        
        if self._phase_col == None:
            self.assign_major()
        else:
            self._normalized_dataframe['MAJOR'] = self._dataframe[self._phase_col]
        

        self._normalized_dataframe = self._normalized_dataframe[[
            'UID',
            'LENGTH_NORM',
            "HOLE_DIRECTION",
            'MAJOR',
            'T_INDEX',
            'NORMALIZED_OIL',
            'NORMALIZED_GAS',
            'NORMALIZED_WATER'
        ]]

        self._normalized_dataframe['NORMALIZED_OIL'] = self._normalized_dataframe['NORMALIZED_OIL'].fillna(0) 
        self._normalized_dataframe['NORMALIZED_GAS'] = self._normalized_dataframe['NORMALIZED_GAS'].fillna(0) 
        self._normalized_dataframe['NORMALIZED_WATER'] = self._normalized_dataframe['NORMALIZED_WATER'].fillna(0) 
    
        if self.DEBUG_ON:
            self._normalized_dataframe.to_csv('outputs/norm_test.csv')
    
    def outlier_detection(self, input_x, input_y):

        
        filtered_x = []
        filtered_y = []
    
        ln_input_y= np.log(input_y)

        if len([i for i in ln_input_y if i > 0]) > 0:
            
            regression = sm.formula.ols("data ~ x", data=dict(data=ln_input_y, x=input_x)).fit()
            try:
                test = regression.outlier_test()
                
                for index, row in test.iterrows():
                    if row['bonf(p)']> self.FILTER_BONFP:
                        filtered_x.append(input_x[index])
                        filtered_y.append(input_y[index])
            except:
                if self.verbose:
                    print('Error in outlier detection.')
                filtered_x = input_x
                filtered_y = input_y

        return filtered_x, filtered_y

    def arps_decline(self,x,qi,di,b,t0):
        if qi > 0 and not math.isinf(qi):
            problemX = t0-1/(b*di)
            #print(di,self.D_MIN,b,qi)
            if di < self.D_MIN:
                qlim = qi
                di = self.D_MIN
                tlim = -1
            else:
                qlim = qi*(self.D_MIN/di)**(1/b)
                #print(qlim)
                try:
                    tlim = int(((qi/qlim)**(b)-1)/(b*di)+t0)
                    #q_at_lim = (qi)/(1+b*(di)*(int(tlim)-t0))**(1/b)
                except:
                    #tlim=-1
                    print(qi,qlim,di,b)
            #problemX = t0+1
            #print(tlim)
            try:
                q_x = np.where(
                    x>problemX,
                    np.where(x<tlim,
                        (qi)/(1+b*(di)*(x-t0))**(1/b),
                        qlim*np.exp(-self.D_MIN*(x-tlim))
                    ),
                    0
                )
            except Exception as e:
                print(qi,qlim,di,b)
                raise e
            #print(q_x)
            #qi = (qi)/(1+b*(ai)*(x))**(1/b)
        else:
            q_x = [0.0 for _ in x]
        return q_x
    
    def handle_dca_error(self,s,x_vals,y_vals):
        if s["MAJOR"] == 'OIL':
            #print(sum_df)
            minor_ratio = np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL:])
            water_ratio = np.sum(s['NORMALIZED_WATER'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL:])
        else:
            minor_ratio = np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL:])
            water_ratio = np.sum(s['NORMALIZED_WATER'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL:])
        i = -1
        while i > -len(x_vals):
            if y_vals[i]>0:
                break
            else:
                i -= 1
        s['qi']=y_vals[i]
        s['di']=self.DEFAULT_DI
        s['b']=self.DEFAULT_B
        s['t0']=x_vals[i]
        s['q0']=y_vals[0] #Probably will need revision, high chance first value is zero
        s['minor_ratio']=minor_ratio
        s['water_ratio']=water_ratio

        return s

    def dca_params(self,s):

        x_vals = s['T_INDEX']

        if s['MAJOR'] == 'OIL':
            y_vals = s['NORMALIZED_OIL']
        else:
            y_vals = s['NORMALIZED_GAS']

        if len(x_vals) > 3:
            z = np.array(y_vals)
            a = argrelextrema(z, np.greater)
            if len(a[0]) > 0:
                indexMax = a[-1][-1]
                indexMin = a[-1][0]
                t0Max = x_vals[indexMax]
                t0Min = x_vals[indexMin]
            else:
                indexMax = 0
                indexMin = 0
                t0Max = x_vals[indexMax]
                t0Min = x_vals[indexMin]
            

            filtered_x = np.array(x_vals[indexMin:])
            filtered_y = np.array(y_vals[indexMin:])

            zero_filter = np.array([y > 0 for y in filtered_y])
            filtered_x = filtered_x[zero_filter]
            filtered_y = filtered_y[zero_filter]
            
            outliered_x, outliered_y = self.outlier_detection(filtered_x,filtered_y)

            if self._force_t0:
                outliered_x = x_vals
                outliered_y = y_vals

            

            if len(outliered_x) > 3:
                if t0Min == t0Max:
                    t0Max = t0Max + 1
                try:
                    di_int = np.log(outliered_y[0]/outliered_y[-1])/(outliered_x[-1]-outliered_x[0])
                except ZeroDivisionError:
                    di_int = .1
                except Exception as e:
                    raise(e)
                q_max = np.max(outliered_y)
                q_min = np.min(outliered_y)

                if s['HOLE_DIRECTION'] == 'H':
                    bMin = self._min_h_b
                    bMax = self._max_h_b
                else:
                    bMin = self._min_h_b
                    bMax = self._max_h_b

                if di_int < 0:
                    di_int = np.log(q_max/q_min)/(outliered_x[outliered_y.index(q_min)]-outliered_x[outliered_y.index(q_max)])
                
                if di_int < 0:
                    if q_max == outliered_y[-1]:
                        di_int = .1
                    else:
                        di_int = np.log(q_max/outliered_y[-1])/(outliered_x[-1]-outliered_x[outliered_y.index(q_max)])
                
                if self._force_t0:
                    weight_range = [1 for _ in range(1,len(outliered_x)+1)]
                    #weight_range = list(range(1,len(outliered_x)+1))
                    di_min = .01
                    di_max = .9
                    t0Min = 1
                    t0Max = 2
                else:
                    di_min = di_int/2
                    di_max = di_int*2
                    weight_range = list(range(1,len(outliered_x)+1))
                    weight_range = weight_range[::-1]
                
                try:
                    popt, pcov = curve_fit(self.arps_decline, outliered_x, outliered_y,
                        p0=[q_max, di_int,(bMin+bMax)/2,t0Min], 
                        bounds=([q_min,di_min,bMin, t0Min], [q_max*1.1,di_max,bMax,t0Max]),
                        sigma = weight_range, absolute_sigma = True)
                    
                    

                    if s["MAJOR"] == 'OIL':
                        #print(sum_df)
                        minor_ratio = np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL:])
                        if self.verbose:
                            print(f'Minor Ratio: {minor_ratio}')
                        water_ratio = np.sum(s['NORMALIZED_WATER'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL:])
                        if self.verbose:
                            print(f'Water Ratio: {water_ratio}')
                    else:
                        minor_ratio = np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL:])
                        water_ratio = np.sum(s['NORMALIZED_WATER'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL:])

                    if not math.isinf(popt[0]):

                        s['qi']=popt[0]
                        s['di']=popt[1]
                        s['b']=popt[2]
                        s['t0']=popt[3]
                        s['q0']=y_vals[0] #Probably will need revision, high chance first value is zero
                        s['minor_ratio']=minor_ratio
                        s['water_ratio']=water_ratio
                    else:
                        self.V_DCA_FAILURES += 1
                        if self.verbose:
                            print('DCA Error: '+str(s['UID']), file=self.STAT_FILE, flush=True)

                        if self._backup_decline:
                            #local_df = self._normalized_dataframe.loc[self._normalized_dataframe['UID'] == w]
                            #sum_df = local_df.tail(self.MINOR_TAIL).sum()
                            return self.handle_dca_error(s,x_vals, y_vals)
                except:
                    self.V_DCA_FAILURES += 1
                    if self.verbose:
                        print('DCA Error: '+str(s['UID']), file=self.STAT_FILE, flush=True)

                    if self._backup_decline:
                        #local_df = self._normalized_dataframe.loc[self._normalized_dataframe['UID'] == w]
                        #sum_df = local_df.tail(self.MINOR_TAIL).sum()
                        return self.handle_dca_error(s,x_vals, y_vals)
            else:
                self.V_DCA_FAILURES += 1
                if self.verbose:
                    print('Base x: {}  Filtered x: {}  Outliered x: {}'.format(len(x_vals),len(filtered_x),len(outliered_x)))
                    print('Insufficent data after filtering, well: '+str(s['UID']), file=self.STAT_FILE, flush=True)
                if self._backup_decline:
                    return self.handle_dca_error(s,x_vals, y_vals)

        else :
            self.V_DCA_FAILURES += 1
            if self.verbose:
                print('Insufficent data before filtering, well: '+str(s['UID']), file=self.STAT_FILE, flush=True)
            if self._backup_decline:
                return self.handle_dca_error(s,x_vals, y_vals)

        #print(s)
        return s
    
    def vect_generate_params_tc(self,param_df):

        self._force_t0 = True

        param_df['HOLE_DIRECTION'] = "H"
        param_df = param_df[param_df['T_INDEX']<60]
        param_df = param_df.rename(columns={
            'OIL':'NORMALIZED_OIL',
            'GAS':"NORMALIZED_GAS",
            'WATER':'NORMALIZED_WATER',
            'level_1':'UID'
        })

        imploded_df = param_df[[
            'UID',
            'MAJOR',
            'HOLE_DIRECTION',
            'T_INDEX',
            'NORMALIZED_OIL',
            'NORMALIZED_GAS',
            'NORMALIZED_WATER'
        ]].groupby(
            ['UID',
            'MAJOR',
            'HOLE_DIRECTION']
        ).agg({
            'T_INDEX': lambda x: x.tolist(),
            'NORMALIZED_OIL': lambda x: x.tolist(),
            'NORMALIZED_GAS': lambda x: x.tolist(),
            'NORMALIZED_WATER': lambda x: x.tolist()
        }).reset_index()

        imploded_df = imploded_df.apply(self.dca_params, axis=1)
        imploded_df = imploded_df[[
            'UID',
            'MAJOR',
            'q0',
            'qi',
            'di',
            'b',
            't0',
            'minor_ratio',
            'water_ratio',
        ]].rename(columns={
            'MAJOR':'major',
        })

        self._force_t0 = False

        return imploded_df



    def vect_generate_params(self):
        self.V_DCA_FAILURES = 0
        l_start = time.time()

        imploded_df = self._normalized_dataframe[[
            'UID',
            'MAJOR',
            'HOLE_DIRECTION',
            'LENGTH_NORM',
            'T_INDEX',
            'NORMALIZED_OIL',
            'NORMALIZED_GAS',
            'NORMALIZED_WATER'
        ]].groupby(
            ['UID',
            'MAJOR',
            'HOLE_DIRECTION',
            'LENGTH_NORM']
        ).agg({
            'T_INDEX': lambda x: x.tolist(),
            'NORMALIZED_OIL': lambda x: x.tolist(),
            'NORMALIZED_GAS': lambda x: x.tolist(),
            'NORMALIZED_WATER': lambda x: x.tolist()
        }).reset_index()

        imploded_df = imploded_df.apply(self.dca_params, axis=1)

        imploded_df = imploded_df[[
            'UID',
            'MAJOR',
            'LENGTH_NORM',
            'q0',
            'qi',
            'di',
            'b',
            't0',
            'minor_ratio',
            'water_ratio',
        ]].rename(columns={
            'MAJOR':'major',
            'LENGTH_NORM':'h_length'
        })

        r_df:pd.DataFrame = pd.DataFrame([])

        for major in ['OIL','GAS']:
            l_df = imploded_df[imploded_df['major']==major]

            if len(l_df)>0:
                if self.OUTLIER_CORRECTION:
                    q3, q2, q1 = np.percentile(l_df['minor_ratio'], [75,50 ,25])
                    high_cutoff = self.IQR_LIMIT*(q3-q1)+q3
                    l_df['minor_ratio'] = np.where(
                        l_df['minor_ratio']>high_cutoff,
                        q2,
                        l_df['minor_ratio']
                    )

                    q3, q2, q1 = np.percentile(l_df['water_ratio'], [75,50 ,25])
                    high_cutoff = self.IQR_LIMIT*(q3-q1)+q3
                    l_df['water_ratio'] = np.where(
                        l_df['water_ratio']>high_cutoff,
                        q2,
                        l_df['water_ratio']
                    )

                if r_df.empty:
                    r_df = l_df
                else:
                    r_df = pd.concat([r_df,l_df])

        imploded_df = r_df

        print('Total DCA Failures: '+str(self.V_DCA_FAILURES), file=self.STAT_FILE, flush=True)
        print(f'Total wells analyzed: {len(imploded_df)}', file=self.STAT_FILE, flush=True)
        print('Failure rate: {:.2%}'.format(self.V_DCA_FAILURES/len(imploded_df)), file=self.STAT_FILE, flush=True)
        l_duration = time.time() - l_start
        print("Vectorized DCA generation: {:.2f} seconds".format(l_duration), file=self.STAT_FILE, flush=True)

        self._params_dataframe = imploded_df


    def run_DCA(self, _verbose=True):
        self.verbose = _verbose
        if self.verbose:
            print('Generating time index.', file=self.STAT_FILE, flush=True)
            
        
        self.generate_t_index()

        if self.verbose:
            print('Normalizing production.', file=self.STAT_FILE, flush=True)

        self.normalize_production()

        if self.verbose:
            print('Generating decline parameters.', file=self.STAT_FILE, flush=True)
        #self.generate_params()
        
        self.vect_generate_params()

    def add_months(self, start_date, delta_period):
        end_date = start_date + pd.DateOffset(months=delta_period)
        return end_date
    
    def generate_oneline(self, num_months=1200, denormalize=False, _verbose=False):
        self.verbose = _verbose

        self.generate_flowstream(num_months=num_months,denormalize=denormalize,actual_dates=False,_verbose=_verbose)

        if self._params_dataframe.empty:
            self.run_DCA(_verbose=_verbose)

        t_range = np.array(range(1,num_months))

        flow_dict = {
            'UID':[],
            'MAJOR':[],
            "IPO":[],
            'IPG':[],
            'B':[],
            'DE':[],
            'T0':[],
            'MINOR_RATIO':[],
            'WATER_RATIO':[]
        }

        #param_df = self.vect_generate_params_tc(self._flowstream_dataframe)

        online_df = self._flowstream_dataframe[['UID','OIL',"GAS",'WATER']].groupby('UID').sum().reset_index()


        self._dataframe[self._date_col] = pd.to_datetime(self._dataframe[self._date_col])

        min_df = self._dataframe[[self._uid_col,self._date_col]].groupby(by=[self._uid_col]).min().reset_index()
        #min_df = self._flowstream_dataframe.groupby(['UID']).min().reset_index()
        min_df = min_df.rename(columns={self._uid_col:"UID",self._date_col:"MIN_DATE"})
        min_df = min_df[min_df['MIN_DATE'].notnull()]

        self._params_dataframe = self._params_dataframe.merge(min_df, left_on='UID', right_on='UID')

        self._params_dataframe = self._params_dataframe.replace([np.inf, -np.inf], np.nan)

        self._params_dataframe = self._params_dataframe.dropna(subset='t0')

        self._params_dataframe['T0_DATE'] =  self._params_dataframe.apply(lambda row: self.add_months(row["MIN_DATE"], round(row["t0"],0)), axis = 1)

        #print(self._params_dataframe)

        for index, row in self._params_dataframe.iterrows():
            if denormalize and row['h_length']>1:
                denormalization_scalar = row['h_length']/self.SET_LENGTH
            else:
                denormalization_scalar = 1
            
            dca = self._flowstream_dataframe[self._flowstream_dataframe['UID']==row['UID']]

            

            if np.sum(dca[row['major']]) > 0:

                flow_dict['UID'].append(row['UID'])
                flow_dict['MAJOR'].append(row['major'])
                
                flow_dict['B'].append(row['b'])
                flow_dict['DE'].append(row['di'])
                flow_dict['T0'].append(row['T0_DATE'])
                flow_dict['MINOR_RATIO'].append(row['minor_ratio'])
                flow_dict['WATER_RATIO'].append(row['water_ratio'])
                if row['major'] == "OIL":
                    #flow_dict['IPO'].append(max(dca[row['major']]))
                    flow_dict['IPO'].append(row['qi']*denormalization_scalar)
                    if np.isnan(row['minor_ratio']):
                        flow_dict['IPG'].append(max(dca[row['major']])*0)
                    else:
                        #flow_dict['IPG'].append(max(dca[row['major']])*row['minor_ratio'])
                        flow_dict['IPG'].append(row['qi']*row['minor_ratio'])
                else:
                    #flow_dict['IPG'].append(max(dca[row['major']]))
                    flow_dict['IPG'].append(row['qi']*denormalization_scalar)
                    if np.isnan(row['minor_ratio']):
                        flow_dict['IPO'].append(max(dca[row['major']])*0)
                    else:
                        #flow_dict['IPO'].append(max(dca[row['major']])*row['minor_ratio'])
                        flow_dict['IPO'].append(row['qi']*row['minor_ratio'])
        flow_dict = pd.DataFrame(flow_dict)
        online_df = online_df.merge(flow_dict,left_on='UID',right_on='UID')
        online_df['ARIES_DE'] = online_df.apply(lambda x: (1-np.power(((x.DE*12)*x.B+1),(-1/x.B)))*100, axis=1)
        self._oneline = online_df

    def generate_flowstream(self, num_months=1200, denormalize=False, actual_dates=False, _verbose=False):
        self.verbose = _verbose

        if self._params_dataframe.empty:
            self.run_DCA(_verbose=_verbose)

        t_range = np.array(range(1,num_months))

        flow_dict = {
            'UID':[],
            'MAJOR':[],
            'T_INDEX':[],
            'OIL':[],
            'GAS':[],
            'WATER':[]
        }


        for index, row in self._params_dataframe.iterrows():
            if denormalize and row['h_length']>1:
                denormalization_scalar = row['h_length']/self.SET_LENGTH
            else:
                denormalization_scalar = 1
            
            dca = np.array(self.arps_decline(t_range,row.qi,row.di,row.b,row.t0))*denormalization_scalar
            if np.sum(dca) > 0:
                flow_dict['UID'].append(row['UID'])
                flow_dict['MAJOR'].append(row['major'])
                flow_dict['T_INDEX'].append(t_range)
                if row['major'] == "OIL":
                    flow_dict['OIL'].append(dca)
                    if np.isnan(row['minor_ratio']):
                        flow_dict['GAS'].append(dca*0)
                    else:
                        flow_dict['GAS'].append(dca*row['minor_ratio'])
                else:
                    flow_dict['GAS'].append(dca)
                    if np.isnan(row['minor_ratio']):
                        flow_dict['OIL'].append(dca*0)
                    else:
                        flow_dict['OIL'].append(dca*row['minor_ratio'])
                if np.isnan(row['water_ratio']):
                    flow_dict['WATER'].append(dca*0)
                else:
                    flow_dict['WATER'].append(dca*row['water_ratio'])

        self._flowstream_dataframe = pd.DataFrame(flow_dict)
        #print(self._flowstream_dataframe.columns)
        self._flowstream_dataframe = self._flowstream_dataframe.set_index(['UID','MAJOR']).apply(pd.Series.explode).reset_index()
        self._flowstream_dataframe = self._flowstream_dataframe.set_index(['UID', 'T_INDEX'])

        self._flowstream_dataframe['OIL'] = pd.to_numeric(
            self._flowstream_dataframe['OIL']
        )

        self._flowstream_dataframe['GAS'] = pd.to_numeric(
            self._flowstream_dataframe['GAS']
        )

        self._flowstream_dataframe['WATER'] = pd.to_numeric(
            self._flowstream_dataframe['WATER']
        )

        self._flowstream_dataframe.replace([np.inf, -np.inf], 0, inplace=True)

        if denormalize:
            actual_df = self._dataframe[[self._uid_col,'T_INDEX',self._oil_col,self._gas_col,self._water_col]]
            actual_df = actual_df.rename(columns={
                self._uid_col:'UID',
                self._oil_col:'OIL',
                self._gas_col:"GAS",
                self._water_col:"WATER"
            })
        else:
            actual_df = self._normalized_dataframe[[
                'UID',
                'T_INDEX',
                'NORMALIZED_OIL',
                'NORMALIZED_GAS',
                'NORMALIZED_WATER'
            ]]
            actual_df = actual_df.rename(columns={
                'NORMALIZED_OIL':'OIL',
                'NORMALIZED_GAS':"GAS",
                'NORMALIZED_WATER':'WATER'
            })

        if actual_dates:
            actual_df['P_DATE'] = self._dataframe[self._date_col]
            self._flowstream_dataframe['P_DATE'] = None
            
        # Added to ensure UID and T_INDEX are unique
    
        actual_df = actual_df.set_index(['UID', 'T_INDEX'])

        #actual_df.to_csv('outputs/actual.csv')
        #self._flowstream_dataframe.to_csv('outputs/flowstrems.csv')

        #self._flowstream_dataframe.to_csv('outputs/flowstream_df.csv')
        #actual_df.to_csv('outputs/actual.csv')
        actual_df = actual_df[~actual_df.index.duplicated(keep='first')]
        self._flowstream_dataframe = self._flowstream_dataframe[~self._flowstream_dataframe.index.duplicated(keep='first')]
        self._flowstream_dataframe.update(actual_df)
        self._flowstream_dataframe = self._flowstream_dataframe.reset_index()


        if actual_dates:
            
            # Updated code using the fact that T_INDEX is always referenced to MIN_DATE

            self._flowstream_dataframe['P_DATE'] = pd.to_datetime(self._flowstream_dataframe['P_DATE'])

            min_df = self._dataframe[[self._uid_col,self._date_col]].groupby(by=[self._uid_col]).min().reset_index()
            #min_df = self._flowstream_dataframe.groupby(['UID']).min().reset_index()
            min_df = min_df.rename(columns={self._uid_col:"UID",self._date_col:"MIN_DATE"})
            min_df = min_df[min_df['MIN_DATE'].notnull()]

            self._flowstream_dataframe = self._flowstream_dataframe.merge(min_df, left_on='UID', right_on='UID')

            self._flowstream_dataframe = self._flowstream_dataframe.replace([np.inf, -np.inf], np.nan)

            self._flowstream_dataframe['P_DATE'] = np.where(
                self._flowstream_dataframe['P_DATE'].isnull(),
                self._flowstream_dataframe.apply(lambda row: self.add_months(row["MIN_DATE"], row["T_INDEX"]), axis = 1),
                self._flowstream_dataframe['P_DATE']
            )

            self._flowstream_dataframe = self._flowstream_dataframe.drop(['MIN_DATE'],axis=1)

            # Orginal code encountered issues when date skips in historical were present

            #self._flowstream_dataframe['P_DATE'] = pd.to_datetime(self._flowstream_dataframe['P_DATE'])
            
            #cum_count = self._flowstream_dataframe[self._flowstream_dataframe['P_DATE'].isnull()].groupby(['UID']).cumcount().rename('OFFSET_INDEX')
            #cum_count = cum_count+1
            #self._flowstream_dataframe = self._flowstream_dataframe.merge(cum_count,how='left', left_index=True, right_index=True)
            
            #max_df = self._flowstream_dataframe.groupby(['UID']).max().reset_index()
            #max_df = max_df[['UID','P_DATE']].rename(columns={'P_DATE':'MAX_DATE'})
            #max_df = max_df[max_df['MAX_DATE'].notnull()]
            
            #self._flowstream_dataframe = self._flowstream_dataframe.merge(max_df, left_on='UID', right_on='UID')
            
            #self._flowstream_dataframe = self._flowstream_dataframe.replace([np.inf, -np.inf], np.nan)
            
            #self._flowstream_dataframe['OFFSET_INDEX'] = self._flowstream_dataframe['OFFSET_INDEX'].fillna(0)

            #self._flowstream_dataframe['P_DATE'] = np.where(
            #    self._flowstream_dataframe['P_DATE'].isnull(),
            #    self._flowstream_dataframe.apply(lambda row: self.add_months(row["MAX_DATE"], row["OFFSET_INDEX"]), axis = 1),
            #    self._flowstream_dataframe['P_DATE']
            #)

            #self._flowstream_dataframe = self._flowstream_dataframe.drop(['OFFSET_INDEX','MAX_DATE'],axis=1)

    def generate_typecurve(self, num_months=1200, denormalize=False, prob_levels=[.1,.5,.9], _verbose=False, return_params=False):
        if self._flowstream_dataframe == None:
            self.generate_flowstream(num_months=num_months,denormalize=denormalize, _verbose=_verbose)

        return_df = self._flowstream_dataframe.reset_index()
        
        #print(return_df.head())
        #return_df = self._flowstream_dataframe[['T_INDEX','OIL','GAS','WATER']]
        if self.DEBUG_ON:
            return_df.to_csv('outputs/test_quantiles.csv')
        
        #print(self._flowstream_dataframe)

        return_df = self._flowstream_dataframe[['T_INDEX','OIL','GAS','WATER']].groupby(['T_INDEX']).quantile(prob_levels).reset_index()
        avg_df = self._flowstream_dataframe[['T_INDEX','OIL','GAS','WATER']].groupby(['T_INDEX']).mean().reset_index()
        avg_df['level_1'] = 'mean'
        return_df = pd.concat([return_df,avg_df])
        #vect_df = self._flowstream_dataframe[['T_INDEX','MAJOR','OIL','GAS','WATER']].groupby(['T_INDEX','MAJOR']).quantile(prob_levels).reset_index()

        
        if return_params:
            r_df = pd.DataFrame([])
            for major in ['OIL','GAS']:
            #return_df.to_csv('outputs/return_test.csv')
                l_df = return_df.copy()
                l_df['MAJOR'] = major
                param_df = self.vect_generate_params_tc(l_df)
                param_df['d0'] = param_df.apply(lambda x: x.di*np.power((1+x.b*x.di*(1-x.t0)),-1), axis=1)
                #param_df['d0_a'] = param_df.apply(lambda x: np.power((1+x.d0),12)-1, axis=1)
                param_df['d0_a'] = param_df.apply(lambda x: x.d0*12, axis=1)
                param_df['aries_de'] = param_df.apply(lambda x: (1-np.power((x.d0_a*x.b+1),(-1/x.b)))*100, axis=1)
                param_df = param_df.rename(columns={
                    'qi':'Actual Initial Rate, bbl/month',
                    'q0':'DCA Initial Rate, bbl/month',
                    'di':'Nominal Initial Decline at Match Point, fraction/months',
                    'b':'B Factor, unitless',
                    't0':'Match Point, months',
                    'minor_ratio':'Minor Phase Ratio, (M/B or B/M)',
                    'water_ratio':'Water Phase Ratio (B/B or B/M)',
                    'd0':'Nominal Initial Decline at Time Zero, fraction/months',
                    'd0_a':'Nominal Initial Decline at Time Zero, fraction/years',
                    'aries_de':'Effective Initial Decline at Time Zero, %/years (FOR ARIES)',
                    'UID':'Probability',
                    'major':'Major Phase'
                })
                if r_df.empty:
                    r_df = param_df
                else:
                    r_df = pd.concat([r_df,param_df])
            self.tc_params = r_df
        return_df = return_df.pivot(
                index=['T_INDEX'],
                columns='level_1',
                values=['OIL','GAS','WATER']
            )
            #oil_df.columns = ['P10 Oil, bbl/(km-month)','P50 Oil, bbl/(km-month)','P90 Oil, bbl/(km-month)']
        #oil_df = oil_df.rename(columns={'T_INDEX':'Months Online'})

        self._typecurve = return_df


if __name__ == '__main__':

    l_dca = decline_solver(
        qi=16805,
        qf=3000,
        eur=1104336.17516371,
        b=.01,
        dmin=.01/12
    )

    print(l_dca.solve())
