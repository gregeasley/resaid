"""
Reservoir Engineering Decline Curve Analysis (DCA) Module

This module provides comprehensive decline curve analysis tools for oil and gas production forecasting.
It supports both traditional single-phase (major phase) analysis and advanced three-phase forecasting.

Classes:
    decline_solver: Solver for decline curve parameter optimization
    decline_curve: Main DCA class for production analysis and forecasting

Features:
    - Arps decline curve analysis (exponential, hyperbolic, harmonic)
    - Production data normalization and outlier detection
    - Single-phase and three-phase forecasting modes
    - Flowstream, oneline, and typecurve generation
    - Vectorized operations for improved performance
"""

import pandas as pd
import numpy as np
import sys
import statsmodels.api as sm
from scipy.signal import argrelextrema
from scipy.optimize import curve_fit, fsolve
from dateutil.relativedelta import relativedelta
import time
import warnings

warnings.simplefilter("ignore")

class decline_solver:
    """
    Decline curve parameter solver for optimization problems.
    
    This class solves for missing decline curve parameters given constraints
    on initial rate, final rate, decline rate, b-factor, EUR, and time horizon.
    
    Attributes:
        qi: Initial production rate
        qf: Final production rate
        de: Decline rate
        dmin: Minimum decline rate
        b: Arps b-factor
        eur: Estimated ultimate recovery
        t_max: Maximum time horizon
    """

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
        """
        Determine which variables need to be solved based on provided parameters.
        
        Uses conditional logic to identify missing parameters and sets initial estimates
        for the optimization solver.
        """
        # Check which parameters are missing and set up initial estimates
        if self.qi is None and self.qf is None:
            self.variables_to_solve = ['qi']
            self.qi = self.de * self.eur / 2
            self.qf = 1
        elif self.qi is None and self.de is None:
            self.variables_to_solve = ['qi', 'de']
            # Set initial estimates for both variables
            self.qi = self.qf + self.dmin * self.eur
            self.de = self.dmin
        elif self.qi is None and self.eur is None:
            self.variables_to_solve = ['qi', 'eur']
            # Set initial estimates for both variables
            self.qi = self.qf * 2  # Reasonable initial guess
            self.eur = self.qi * 100  # Reasonable initial guess
        elif self.qi is None and self.t_max is None:
            self.variables_to_solve = ['qi']
            self.qi = self.qf + self.de * self.eur
            self.t_max = 1200
        elif self.t_max is None and self.qf is None:
            self.variables_to_solve = ['qf']
            self.qf = max(self.qi - self.de * self.eur, 1)
            self.t_max = 1200
        elif self.t_max is None and self.de is None:
            self.variables_to_solve = ['de']
            self.de = (self.qi - self.qf) / self.eur
            self.t_max = 1200
        elif self.t_max is None and self.eur is None:
            self.variables_to_solve = ['eur']
            self.t_max = 1200
            self.eur = (self.qi - self.qf) / self.de
        elif self.qf is None and self.de is None:
            self.variables_to_solve = ['de']
            self.de = self.qi / self.eur
            self.qf = 1
        elif self.qf is None and self.eur is None:
            self.variables_to_solve = ['eur']
            self.eur = self.qi / self.de
            self.qf = 1
        elif self.de is None and self.eur is None:
            self.variables_to_solve = ['de', 'eur']
            # Set initial estimates for both variables
            self.de = self.dmin
            self.eur = self.qi * self.t_max
        # Handle cases where only one parameter is missing
        elif self.qi is None:
            self.variables_to_solve = ['qi']
            self.qi = self.qf + self.de * self.eur
        elif self.qf is None:
            self.variables_to_solve = ['qf']
            self.qf = max(self.qi - self.de * self.eur, 1)
        elif self.de is None:
            self.variables_to_solve = ['de']
            self.de = (self.qi - self.qf) / self.eur
        elif self.eur is None:
            self.variables_to_solve = ['eur']
            self.eur = (self.qi - self.qf) / self.de
        elif self.t_max is None:
            self.variables_to_solve = ['t_max']
            self.t_max = 1200
        else:
            self.variables_to_solve = []
        
        # Set default t_max if still None
        if self.t_max is None:
            self.t_max = 1200


    def dca_delta(self, vars_to_solve):
        """
        Calculate the objective function for parameter optimization.
        
        Args:
            vars_to_solve: List of parameter values to evaluate
            
        Returns:
            float: Objective function value (sum of squared residuals)
        """
        for var_name, var_value in zip(self.variables_to_solve, vars_to_solve):
            setattr(self, var_name, var_value)

        self.l_dca.D_MIN = self.dmin
        t_range = np.array(range(0, int(self.t_max)))

        dca_array = np.array(self.l_dca.arps_decline(t_range, self.qi, self.de, self.b, 0))
        dca_array = np.where(dca_array > self.qf, dca_array, 0)

        self.l_t_max = len(np.where(dca_array > 0)[0])
        if self.l_t_max > 0:
            # Calculate cumulative production and compare with EUR
            cumulative_production = np.sum(dca_array)
            self.delta = abs(cumulative_production - self.eur)
        else:
            self.delta = 1e10
            
        return self.delta

    def solve(self):
        """
        Solve for optimal decline curve parameters.
        
        Returns:
            tuple: (qi, t_max, qf, de, eur, warning_flag, delta)
        """
        self.determine_solve()
        
        if len(self.variables_to_solve) == 0:
            return self.qi, self.t_max, self.qf, self.de, self.eur, False, self.delta
        
        try:
            result = fsolve(self.dca_delta, [getattr(self, var) for var in self.variables_to_solve])
            warning_flag = False
        except:
            warning_flag = True
            result = [getattr(self, var) for var in self.variables_to_solve]
            
        for var_name, var_value in zip(self.variables_to_solve, result):
            setattr(self, var_name, var_value)
            
        if self.qf is None:
            self.qf = self.l_qf
        return self.qi, self.t_max, self.qf, self.de, self.eur, warning_flag, self.delta


class decline_curve:
    """
    Main decline curve analysis class for production forecasting.
    
    This class provides comprehensive decline curve analysis capabilities including:
    - Production data preprocessing and normalization
    - Arps decline curve parameter fitting
    - Single-phase and three-phase forecasting modes
    - Flowstream, oneline, and typecurve generation
    
    Attributes:
        DAY_NORM: Days per month normalization factor
        GAS_CUTOFF: Gas-oil ratio cutoff for phase classification (MSCF/STB)
        SET_LENGTH: Standard lateral length for normalization (ft)
        D_MIN: Minimum monthly decline rate
        DEFAULT_DI: Default initial decline rate
        DEFAULT_B: Default Arps b-factor
        three_phase_mode: Enable three-phase forecasting mode
    """

    def __init__(self):
        # Constants
        self.DAY_NORM = 365/12
        self.GAS_CUTOFF = 3.2  # GOR for classifying well as gas or oil, MSCF/STB
        self.STAT_FILE = sys.stdout
        self.MINOR_TAIL = 6  # Number of months from tail to use for minor phase ratios
        self.SET_LENGTH = 5280  # Length to normalize horizontals to
        self.D_MIN = .08/12  # Minimum monthly decline rate
        self.DEBUG_ON = False
        
        # Settable parameters
        self.verbose = True
        self.FILTER_BONFP = .5  # Normally set to .5
        self.DEFAULT_DI = .8/12
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

        # Three-phase forecasting mode
        self._three_phase_mode = False

        # Data storage
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
    def three_phase_mode(self):
        return self._three_phase_mode

    @three_phase_mode.setter
    def three_phase_mode(self, value):
        self._three_phase_mode = value

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
        """Generate time index for production data."""
        self._dataframe[self._date_col] = pd.to_datetime(self._dataframe[self._date_col])
        min_by_well = self._dataframe[[self._uid_col,self._date_col]].groupby(by=[self._uid_col]).min().reset_index()
        min_by_well = min_by_well.rename(columns={self._date_col:'MIN_DATE'})
        
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
        """Assign major phase (OIL or GAS) based on gas-oil ratio."""
        l_cum = self._normalized_dataframe[['UID','NORMALIZED_OIL','NORMALIZED_GAS']].groupby(by=['UID']).sum().reset_index()
        l_cum['MAJOR'] = np.where(
            l_cum["NORMALIZED_OIL"] > 0,
            np.where(
                l_cum["NORMALIZED_GAS"]/l_cum['NORMALIZED_OIL'] > self.GAS_CUTOFF,
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
        """
        Detect and filter outliers using Bonferroni correction.
        
        Args:
            input_x: Time values
            input_y: Production values
            
        Returns:
            tuple: (filtered_x, filtered_y) - filtered data without outliers
        """
        filtered_x = []
        filtered_y = []
    
        ln_input_y = np.log(input_y)

        if len([i for i in ln_input_y if i > 0]) > 0:
            regression = sm.formula.ols("data ~ x", data=dict(data=ln_input_y, x=input_x)).fit()
            try:
                test = regression.outlier_test()
                
                for index, row in test.iterrows():
                    if row['bonf(p)'] > self.FILTER_BONFP:
                        filtered_x.append(input_x[index])
                        filtered_y.append(input_y[index])
            except:
                if self.verbose:
                    print('Error in outlier detection.')
                filtered_x = input_x
                filtered_y = input_y

        return filtered_x, filtered_y

    def arps_decline(self, x, qi, di, b, t0):
        """
        Calculate Arps decline curve production rates.
        
        Args:
            x: Time array
            qi: Initial production rate
            di: Initial decline rate
            b: Arps b-factor
            t0: Time offset
            
        Returns:
            numpy array: Production rates over time
        """
        if qi > 0 and not np.isinf(qi):
            problemX = t0 - 1/(b*di)
            if di < self.D_MIN:
                qlim = qi
                di = self.D_MIN
                tlim = -1
            else:
                qlim = qi*(self.D_MIN/di)**(1/b)
                try:
                    tlim = int(((qi/qlim)**(b)-1)/(b*di)+t0)
                except:
                    if self.verbose:
                        print(f'DCA calculation error: qi={qi}, qlim={qlim}, di={di}, b={b}')
                    tlim = -1
            try:
                q_x = np.where(
                    x > problemX,
                    np.where(x < tlim,
                        (qi)/(1+b*(di)*(x-t0))**(1/b),
                        qlim*np.exp(-self.D_MIN*(x-tlim))
                    ),
                    0
                )
            except Exception as e:
                if self.verbose:
                    print(f'DCA calculation error: qi={qi}, qlim={qlim}, di={di}, b={b}')
                raise e
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
                        minor_ratio = np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL:])
                        water_ratio = np.sum(s['NORMALIZED_WATER'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL:])
                    else:
                        minor_ratio = np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL:])
                        water_ratio = np.sum(s['NORMALIZED_WATER'][-self.MINOR_TAIL:])/np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL:])

                    if not np.isinf(popt[0]):

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
                            return self.handle_dca_error(s,x_vals, y_vals)
                except:
                    self.V_DCA_FAILURES += 1
                    if self.verbose:
                        print('DCA Error: '+str(s['UID']), file=self.STAT_FILE, flush=True)

                    if self._backup_decline:
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

        if self.verbose:
            print('Total DCA Failures: '+str(self.V_DCA_FAILURES), file=self.STAT_FILE, flush=True)
            print(f'Total wells analyzed: {len(imploded_df)}', file=self.STAT_FILE, flush=True)
            print('Failure rate: {:.2%}'.format(self.V_DCA_FAILURES/len(imploded_df)), file=self.STAT_FILE, flush=True)
            l_duration = time.time() - l_start
            print("Vectorized DCA generation: {:.2f} seconds".format(l_duration), file=self.STAT_FILE, flush=True)

        self._params_dataframe = imploded_df

    def vect_generate_params_three_phase(self):
        """
        Generate DCA parameters for each non-zero phase independently.
        This method calculates decline parameters for OIL, GAS, and WATER phases
        separately instead of using ratios from the major phase.
        """
        self.V_DCA_FAILURES = 0
        l_start = time.time()

        all_results = []

        # Group by well to determine which phases have non-zero production for each well
        well_phases = self._normalized_dataframe.groupby('UID').agg({
            'NORMALIZED_OIL': 'sum',
            'NORMALIZED_GAS': 'sum',
            'NORMALIZED_WATER': 'sum'
        }).reset_index()

        # Determine which phases to analyze for each well
        for _, well_row in well_phases.iterrows():
            uid = well_row['UID']
            phases_to_analyze = []
            
            if well_row['NORMALIZED_OIL'] > 0:
                phases_to_analyze.append('OIL')
            if well_row['NORMALIZED_GAS'] > 0:
                phases_to_analyze.append('GAS')
            if well_row['NORMALIZED_WATER'] > 0:
                phases_to_analyze.append('WATER')

            # Get well data for this UID
            well_data = self._normalized_dataframe[self._normalized_dataframe['UID'] == uid]

            for phase in phases_to_analyze:
                # Create a temporary dataframe for this phase-well combination
                temp_df = well_data[[
                    'UID',
                    'HOLE_DIRECTION',
                    'LENGTH_NORM',
                    'T_INDEX',
                    f'NORMALIZED_{phase}'
                ]].copy()
                
                # Add a MAJOR column for this phase
                temp_df['MAJOR'] = phase
                
                # Add dummy columns for other phases (set to 0)
                for other_phase in ['OIL', 'GAS', 'WATER']:
                    if other_phase != phase:
                        temp_df[f'NORMALIZED_{other_phase}'] = 0

                # Group by well characteristics
                imploded_df = temp_df.groupby([
                    'UID',
                    'MAJOR',
                    'HOLE_DIRECTION',
                    'LENGTH_NORM'
                ]).agg({
                    'T_INDEX': lambda x: x.tolist(),
                    'NORMALIZED_OIL': lambda x: x.tolist(),
                    'NORMALIZED_GAS': lambda x: x.tolist(),
                    'NORMALIZED_WATER': lambda x: x.tolist()
                }).reset_index()

                # Apply DCA parameters calculation
                imploded_df = imploded_df.apply(self.dca_params, axis=1)

                # Filter out failed DCA calculations
                imploded_df = imploded_df[imploded_df['qi'].notna()]

                if len(imploded_df) > 0:
                    # Select and rename columns
                    phase_df = imploded_df[[
                        'UID',
                        'MAJOR',
                        'LENGTH_NORM',
                        'qi',
                        'di',
                        'b',
                        't0'
                    ]].rename(columns={
                        'MAJOR': 'phase',
                        'LENGTH_NORM': 'h_length'
                    })
                    
                    # Add phase-specific columns
                    phase_df['minor_ratio'] = 0.0  # No minor ratio in three-phase mode
                    phase_df['water_ratio'] = 0.0  # No water ratio in three-phase mode
                    
                    all_results.append(phase_df)

        # Combine all results
        if all_results:
            imploded_df = pd.concat(all_results, ignore_index=True)
        else:
            imploded_df = pd.DataFrame()

        if self.verbose:
            print('Total DCA Failures: '+str(self.V_DCA_FAILURES), file=self.STAT_FILE, flush=True)
            print(f'Total phase-well combinations analyzed: {len(imploded_df)}', file=self.STAT_FILE, flush=True)
            if len(imploded_df) > 0:
                print('Failure rate: {:.2%}'.format(self.V_DCA_FAILURES/len(imploded_df)), file=self.STAT_FILE, flush=True)
            l_duration = time.time() - l_start
            print("Three-phase DCA generation: {:.2f} seconds".format(l_duration), file=self.STAT_FILE, flush=True)

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
        
        if self.three_phase_mode:
            self.vect_generate_params_three_phase()
        else:
            self.vect_generate_params()

    def add_months(self, start_date, delta_period):
        end_date = start_date + relativedelta(months=delta_period)
        return end_date
    
    def generate_oneline(self, num_months=1200, denormalize=False, _verbose=False):
        self.verbose = _verbose

        self.generate_flowstream(num_months=num_months,denormalize=denormalize,actual_dates=False,_verbose=_verbose)

        if self._params_dataframe.empty:
            self.run_DCA(_verbose=_verbose)

        if self.three_phase_mode:
            self._generate_oneline_three_phase(num_months, denormalize, _verbose)
        else:
            self._generate_oneline_original(num_months, denormalize, _verbose)

    def _generate_oneline_original(self, num_months, denormalize, _verbose):
        """Original oneline generation using major phase with ratios"""
        # Of note, since you often forget this, the flowstream dataframe inherits the denormalize attribute
        # So the oneline sums will always follow the denormalization settings
        oneline_df = self._flowstream_dataframe.reset_index()[['UID','OIL',"GAS",'WATER']].groupby('UID').sum().reset_index()

        self._dataframe[self._date_col] = pd.to_datetime(self._dataframe[self._date_col])

        min_df = self._dataframe[[self._uid_col,self._date_col]].groupby(by=[self._uid_col]).min().reset_index()
        min_df = min_df.rename(columns={self._uid_col:"UID",self._date_col:"MIN_DATE"})
        min_df = min_df[min_df['MIN_DATE'].notnull()]

        self._params_dataframe = self._params_dataframe.merge(min_df, left_on='UID', right_on='UID')

        self._params_dataframe = self._params_dataframe.replace([np.inf, -np.inf], np.nan)

        self._params_dataframe = self._params_dataframe.dropna(subset='t0')

        self._params_dataframe['T0_DATE'] =  self._params_dataframe.apply(lambda row: self.add_months(row["MIN_DATE"], round(row["t0"],0)), axis = 1)

        flow_df = self._params_dataframe[['UID','major','h_length','qi','di','b','T0_DATE','minor_ratio','water_ratio']].copy()

        # Calculate flow_df denormalization_scalar
        if denormalize:
            flow_df['denormalization_scalar'] = np.where(
                flow_df['h_length'] > 1,
                flow_df['h_length'] / self.SET_LENGTH,
                1.0
            )
        else:
            flow_df['denormalization_scalar'] = 1.0

        flow_df = flow_df.rename(columns={
            'major':'MAJOR',
            'b':'B',
            'di':'DE',
            'minor_ratio':'MINOR_RATIO',
            'water_ratio':'WATER_RATIO'
        })
        # Fill na in MINOR_RATIO and WATER_RATIO with 0
        flow_df['MINOR_RATIO'] = flow_df['MINOR_RATIO'].fillna(0)
        flow_df['WATER_RATIO'] = flow_df['WATER_RATIO'].fillna(0)

        flow_df['IPO'] = np.where(
            flow_df['MAJOR'] == "OIL",
            flow_df['qi']*flow_df['denormalization_scalar'],
            flow_df['qi']*flow_df['MINOR_RATIO']*flow_df['denormalization_scalar']
        )

        flow_df['IPG'] = np.where(  
            flow_df['MAJOR'] == "GAS",
            flow_df['qi']*flow_df['denormalization_scalar'],
            flow_df['qi']*flow_df['MINOR_RATIO']*flow_df['denormalization_scalar']
        )
        
        flow_df['WATER'] = flow_df['qi']*flow_df['WATER_RATIO']

        flow_df['ARIES_DE'] = flow_df.apply(lambda row: (1-np.power(((row.DE*12)*row.B+1),(-1/row.B)))*100, axis=1)

        self._oneline = oneline_df.merge(
            flow_df[['UID','MAJOR','IPO','IPG','B','DE','T0_DATE','MINOR_RATIO','WATER_RATIO','ARIES_DE']],
            left_on='UID',
            right_on='UID'
        )

    def _generate_oneline_three_phase(self, num_months, denormalize, _verbose):
        """Three-phase oneline generation with independent decline curves for each phase"""
        # Get flowstream totals by well
        oneline_df = self._flowstream_dataframe.reset_index()[['UID','OIL',"GAS",'WATER']].groupby('UID').sum().reset_index()

        # Get minimum dates for each well
        self._dataframe[self._date_col] = pd.to_datetime(self._dataframe[self._date_col])
        min_df = self._dataframe[[self._uid_col,self._date_col]].groupby(by=[self._uid_col]).min().reset_index()
        min_df = min_df.rename(columns={self._uid_col:"UID",self._date_col:"MIN_DATE"})
        min_df = min_df[min_df['MIN_DATE'].notnull()]

        # Merge with params dataframe
        params_with_dates = self._params_dataframe.merge(min_df, left_on='UID', right_on='UID')
        params_with_dates = params_with_dates.replace([np.inf, -np.inf], np.nan)
        params_with_dates = params_with_dates.dropna(subset='t0')
        params_with_dates['T0_DATE'] = params_with_dates.apply(lambda row: self.add_months(row["MIN_DATE"], round(row["t0"],0)), axis = 1)

        # Create oneline data for each well
        well_summaries = []
        
        for uid in oneline_df['UID'].unique():
            well_params = params_with_dates[params_with_dates['UID'] == uid]
            well_flow = oneline_df[oneline_df['UID'] == uid].iloc[0]
            
            # Initialize well summary
            well_summary = {
                'UID': uid,
                'OIL': well_flow['OIL'],
                'GAS': well_flow['GAS'],
                'WATER': well_flow['WATER'],
                'T0_DATE': well_params['T0_DATE'].iloc[0] if len(well_params) > 0 else None
            }
            
            # Add phase-specific parameters
            for phase in ['OIL', 'GAS', 'WATER']:
                phase_params = well_params[well_params['phase'] == phase]
                if len(phase_params) > 0:
                    param = phase_params.iloc[0]
                    h_length = param['h_length']
                    
                    # Calculate denormalization scalar
                    if denormalize and h_length > 1:
                        denormalization_scalar = h_length / self.SET_LENGTH
                    else:
                        denormalization_scalar = 1.0
                    
                    # Add phase-specific parameters
                    well_summary[f'IP{phase[0]}'] = param['qi'] * denormalization_scalar  # IPO, IPG, IPW
                    well_summary[f'D{phase[0]}'] = param['di']  # DO, DG, DW
                    well_summary[f'B{phase[0]}'] = param['b']   # BO, BG, BW
                    well_summary[f'ARIES_D{phase[0]}'] = (1-np.power(((param['di']*12)*param['b']+1),(-1/param['b'])))*100
                else:
                    # No parameters for this phase
                    well_summary[f'IP{phase[0]}'] = 0.0
                    well_summary[f'D{phase[0]}'] = 0.0
                    well_summary[f'B{phase[0]}'] = 0.0
                    well_summary[f'ARIES_D{phase[0]}'] = 0.0
            
            well_summaries.append(well_summary)
        
        # Create the oneline dataframe
        self._oneline = pd.DataFrame(well_summaries)


    def generate_flowstream(self, num_months=1200, denormalize=False, actual_dates=False, _verbose=False):
        self.verbose = _verbose

        if self._params_dataframe.empty:
            self.run_DCA(_verbose=_verbose)

        t_range = np.array(range(1,num_months))

        if self.three_phase_mode:
            # Three-phase mode: each phase has its own decline curve
            self._generate_flowstream_three_phase(t_range, num_months, denormalize, actual_dates)
        else:
            # Original mode: major phase with ratios
            self._generate_flowstream_original(t_range, num_months, denormalize, actual_dates)

    def _generate_flowstream_original(self, t_range, num_months, denormalize, actual_dates):
        """Original flowstream generation using major phase with ratios"""
        flow_df = self._params_dataframe[['UID','major','h_length','qi','di','b','t0','minor_ratio','water_ratio']].copy()

        flow_df['T_INDEX'] = flow_df.apply(lambda row: t_range, axis=1)
        if denormalize:
            flow_df['denormalization_scalar'] = np.where(
                flow_df['h_length'] > 1,
                    flow_df['h_length'] / self.SET_LENGTH,
                    1.0
                )
        else:
            flow_df['denormalization_scalar'] = 1.0
        
        flow_df['dca_values'] = flow_df.apply(
            lambda row: np.array(self.arps_decline(t_range, row.qi, row.di, row.b, row.t0)) * row['denormalization_scalar'],
            axis=1
        )
        flow_df['OIL'] = np.where(
            flow_df['major'] == "OIL",
            flow_df['dca_values'],
            flow_df['dca_values'] * flow_df['minor_ratio']
        )
        flow_df['GAS'] = np.where(
            flow_df['major'] == "GAS",
            flow_df['dca_values'],
            flow_df['dca_values'] * flow_df['minor_ratio']
        )
        flow_df['WATER'] = flow_df['dca_values'] * flow_df['water_ratio']
        
        self._flowstream_dataframe = flow_df[['UID','major','T_INDEX','OIL','GAS','WATER']].rename(columns={'major':'MAJOR'})
        self._flowstream_dataframe = self._flowstream_dataframe.set_index(['UID','MAJOR']).apply(pd.Series.explode).reset_index()
        self._flowstream_dataframe = self._flowstream_dataframe.set_index(['UID', 'T_INDEX'])

        # Replace na in OIL, GAS, WATER with 0
        self._flowstream_dataframe['OIL'] = self._flowstream_dataframe['OIL'].fillna(0)
        self._flowstream_dataframe['GAS'] = self._flowstream_dataframe['GAS'].fillna(0)
        self._flowstream_dataframe['WATER'] = self._flowstream_dataframe['WATER'].fillna(0)

        self._flowstream_dataframe['OIL'] = pd.to_numeric(self._flowstream_dataframe['OIL'])
        self._flowstream_dataframe['GAS'] = pd.to_numeric(self._flowstream_dataframe['GAS'])
        self._flowstream_dataframe['WATER'] = pd.to_numeric(self._flowstream_dataframe['WATER'])

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
            
        actual_df = actual_df.set_index(['UID', 'T_INDEX'])

    def _generate_flowstream_three_phase(self, t_range, num_months, denormalize, actual_dates):
        """Three-phase flowstream generation with independent decline curves for each phase"""
        # Create a list to store all flow data
        all_flows = []
        
        for _, row in self._params_dataframe.iterrows():
            uid = row['UID']
            phase = row['phase']
            h_length = row['h_length']
            qi = row['qi']
            di = row['di']
            b = row['b']
            t0 = row['t0']
            
            # Calculate denormalization scalar
            if denormalize and h_length > 1:
                denormalization_scalar = h_length / self.SET_LENGTH
            else:
                denormalization_scalar = 1.0
            
            # Calculate DCA values for this phase
            dca_values = np.array(self.arps_decline(t_range, qi, di, b, t0)) * denormalization_scalar
            
            # Create flow data for this phase-well combination
            for t_idx, flow_rate in zip(t_range, dca_values):
                flow_data = {
                    'UID': uid,
                    'T_INDEX': t_idx,
                    'OIL': 0.0,
                    'GAS': 0.0,
                    'WATER': 0.0
                }
                
                # Set the flow rate for the appropriate phase
                if phase == 'OIL':
                    flow_data['OIL'] = flow_rate
                elif phase == 'GAS':
                    flow_data['GAS'] = flow_rate
                elif phase == 'WATER':
                    flow_data['WATER'] = flow_rate
                
                all_flows.append(flow_data)
        
        # Create the flowstream dataframe
        if all_flows:
            self._flowstream_dataframe = pd.DataFrame(all_flows)
            self._flowstream_dataframe = self._flowstream_dataframe.set_index(['UID', 'T_INDEX'])
        else:
            self._flowstream_dataframe = pd.DataFrame(columns=['UID', 'T_INDEX', 'OIL', 'GAS', 'WATER'])
            self._flowstream_dataframe = self._flowstream_dataframe.set_index(['UID', 'T_INDEX'])

        # Replace na values with 0
        self._flowstream_dataframe['OIL'] = self._flowstream_dataframe['OIL'].fillna(0)
        self._flowstream_dataframe['GAS'] = self._flowstream_dataframe['GAS'].fillna(0)
        self._flowstream_dataframe['WATER'] = self._flowstream_dataframe['WATER'].fillna(0)

        # Convert to numeric
        self._flowstream_dataframe['OIL'] = pd.to_numeric(self._flowstream_dataframe['OIL'])
        self._flowstream_dataframe['GAS'] = pd.to_numeric(self._flowstream_dataframe['GAS'])
        self._flowstream_dataframe['WATER'] = pd.to_numeric(self._flowstream_dataframe['WATER'])

        # Replace infinite values
        self._flowstream_dataframe.replace([np.inf, -np.inf], 0, inplace=True)

        # Handle actual data comparison
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
            
        actual_df = actual_df.set_index(['UID', 'T_INDEX'])


    def generate_typecurve(self, num_months=1200, denormalize=False, prob_levels=[.1,.5,.9], _verbose=False, return_params=False):
        if self._flowstream_dataframe == None:
            self.generate_flowstream(num_months=num_months,denormalize=denormalize, _verbose=_verbose)

        if self.three_phase_mode:
            self._generate_typecurve_three_phase(num_months, denormalize, prob_levels, _verbose, return_params)
        else:
            self._generate_typecurve_original(num_months, denormalize, prob_levels, _verbose, return_params)

    def _generate_typecurve_original(self, num_months, denormalize, prob_levels, _verbose, return_params):
        """Original typecurve generation using major phase with ratios"""
        return_df = self._flowstream_dataframe.reset_index()
        
        if self.DEBUG_ON:
            return_df.to_csv('outputs/test_quantiles.csv')
        
        return_df = self._flowstream_dataframe[['T_INDEX','OIL','GAS','WATER']].groupby(['T_INDEX']).quantile(prob_levels).reset_index()
        avg_df = self._flowstream_dataframe[['T_INDEX','OIL','GAS','WATER']].groupby(['T_INDEX']).mean().reset_index()
        avg_df['level_1'] = 'mean'
        return_df = pd.concat([return_df,avg_df])
        
        if return_params:
            r_df = pd.DataFrame([])
            for major in ['OIL','GAS']:
                l_df = return_df.copy()
                l_df['MAJOR'] = major
                param_df = self.vect_generate_params_tc(l_df)
                param_df['d0'] = param_df.apply(lambda x: x.di*np.power((1+x.b*x.di*(1-x.t0)),-1), axis=1)
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

        self._typecurve = return_df

    def _generate_typecurve_three_phase(self, num_months, denormalize, prob_levels, _verbose, return_params):
        """Three-phase typecurve generation with independent decline curves for each phase"""
        return_df = self._flowstream_dataframe.reset_index()
        
        if self.DEBUG_ON:
            return_df.to_csv('outputs/test_quantiles.csv')
        
        # Calculate quantiles and mean for each phase independently
        return_df = self._flowstream_dataframe[['T_INDEX','OIL','GAS','WATER']].groupby(['T_INDEX']).quantile(prob_levels).reset_index()
        avg_df = self._flowstream_dataframe[['T_INDEX','OIL','GAS','WATER']].groupby(['T_INDEX']).mean().reset_index()
        avg_df['level_1'] = 'mean'
        return_df = pd.concat([return_df,avg_df])
        
        if return_params:
            r_df = pd.DataFrame([])
            # In three-phase mode, we have independent parameters for each phase
            for phase in ['OIL','GAS','WATER']:
                l_df = return_df.copy()
                l_df['PHASE'] = phase
                param_df = self.vect_generate_params_tc_three_phase(l_df, phase)
                if len(param_df) > 0:
                    param_df['d0'] = param_df.apply(lambda x: x.di*np.power((1+x.b*x.di*(1-x.t0)),-1), axis=1)
                    param_df['d0_a'] = param_df.apply(lambda x: x.d0*12, axis=1)
                    param_df['aries_de'] = param_df.apply(lambda x: (1-np.power((x.d0_a*x.b+1),(-1/x.b)))*100, axis=1)
                    param_df = param_df.rename(columns={
                        'qi':f'Actual Initial Rate, {phase.lower()}/month',
                        'q0':f'DCA Initial Rate, {phase.lower()}/month',
                        'di':'Nominal Initial Decline at Match Point, fraction/months',
                        'b':'B Factor, unitless',
                        't0':'Match Point, months',
                        'd0':'Nominal Initial Decline at Time Zero, fraction/months',
                        'd0_a':'Nominal Initial Decline at Time Zero, fraction/years',
                        'aries_de':'Effective Initial Decline at Time Zero, %/years (FOR ARIES)',
                        'UID':'Probability',
                        'phase':'Phase'
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

        self._typecurve = return_df

    def vect_generate_params_tc_three_phase(self, param_df, phase):
        """Generate parameters for typecurve in three-phase mode"""
        self._force_t0 = True

        param_df['HOLE_DIRECTION'] = "H"
        param_df = param_df[param_df['T_INDEX']<60]
        param_df = param_df.rename(columns={
            'OIL':'NORMALIZED_OIL',
            'GAS':"NORMALIZED_GAS",
            'WATER':'NORMALIZED_WATER',
            'level_1':'UID'
        })

        # Create a temporary dataframe for this phase
        temp_df = param_df[[
            'UID',
            'HOLE_DIRECTION',
            'T_INDEX',
            f'NORMALIZED_{phase}'
        ]].copy()
        
        # Add a MAJOR column for this phase
        temp_df['MAJOR'] = phase
        
        # Add dummy columns for other phases (set to 0)
        for other_phase in ['OIL', 'GAS', 'WATER']:
            if other_phase != phase:
                temp_df[f'NORMALIZED_{other_phase}'] = 0

        imploded_df = temp_df.groupby([
            'UID',
            'MAJOR',
            'HOLE_DIRECTION'
        ]).agg({
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
            't0'
        ]].rename(columns={
            'MAJOR':'phase'
        })

        self._force_t0 = False

        return imploded_df


if __name__ == '__main__':
    # Example usage of decline_solver
    l_dca = decline_solver(
        qi=16805,
        qf=3000,
        eur=1104336.17516371,
        b=.01,
        dmin=.01/12
    )
    print(l_dca.solve())
