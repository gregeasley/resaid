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
        DAYS_PER_MONTH: Days per month normalization factor
        GAS_CUTOFF: Gas-oil ratio cutoff for phase classification (MSCF/STB)
        STANDARD_LENGTH: Standard lateral length for normalization (ft)
        MIN_DECLINE_RATE: Minimum monthly decline rate
        default_initial_decline: Default initial decline rate
        default_b_factor: Default Arps b-factor
        three_phase_mode: Enable three-phase forecasting mode
    """

    def __init__(self):
        # Constants
        self.DAYS_PER_MONTH = 365/12
        self.GAS_CUTOFF = 3.2  # GOR for classifying well as gas or oil, MSCF/STB
        self.MINOR_TAIL_MONTHS = 6  # Number of months from tail to use for minor phase ratios
        self.STANDARD_LENGTH = 5280  # Length to normalize horizontals to
        self.MIN_DECLINE_RATE = .08/12  # Minimum monthly decline rate
        
        # User-configurable parameters
        self.verbose = True
        self.debug_on = False
        self.STAT_FILE = None  # Enable debug output
        self.filter_bonfp = .5  # Bonferroni correction threshold
        self.default_initial_decline = .8/12
        self.default_b_factor = .5
        self.outlier_correction = True
        self.iqr_limit = 1.5
        self.min_h_b = .99
        self.max_h_b = 2
        
        self.backup_decline = False
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
        self.three_phase_mode = False

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
                self.STANDARD_LENGTH,
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
            self.DAYS_PER_MONTH*
            self._normalized_dataframe['LENGTH_SET'] /
            (self._normalized_dataframe['LENGTH_NORM'] * self._normalized_dataframe['DAYSON'])
        )

        self._normalized_dataframe['NORMALIZED_GAS'] = (
            self._dataframe[self._gas_col]*
            self.DAYS_PER_MONTH*
            self._normalized_dataframe['LENGTH_SET'] /
            (self._normalized_dataframe['LENGTH_NORM'] * self._normalized_dataframe['DAYSON'])
        )

        self._normalized_dataframe['NORMALIZED_WATER'] = (
            self._dataframe[self._water_col]*
            self.DAYS_PER_MONTH*
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
    
        if self.debug_on:
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
                
                outliers_removed = 0
                for index, row in test.iterrows():
                    if row['bonf(p)'] > self.filter_bonfp:
                        filtered_x.append(input_x[index])
                        filtered_y.append(input_y[index])
                    else:
                        outliers_removed += 1
                        
                if self.verbose and outliers_removed > 0:
                    print(f'    Outlier detection: Removed {outliers_removed} points with bonf(p) <= {self.filter_bonfp}')
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
            if di < self.MIN_DECLINE_RATE:
                qlim = qi
                di = self.MIN_DECLINE_RATE
                tlim = -1
            else:
                qlim = qi*(self.MIN_DECLINE_RATE/di)**(1/b)
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
                        qlim*np.exp(-self.MIN_DECLINE_RATE*(x-tlim))
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
            minor_ratio = np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL_MONTHS:])/np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL_MONTHS:])
            water_ratio = np.sum(s['NORMALIZED_WATER'][-self.MINOR_TAIL_MONTHS:])/np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL_MONTHS:])
        else:
            minor_ratio = np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL_MONTHS:])/np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL_MONTHS:])
            water_ratio = np.sum(s['NORMALIZED_WATER'][-self.MINOR_TAIL_MONTHS:])/np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL_MONTHS:])
        i = -1
        while i > -len(x_vals):
            if y_vals[i]>0:
                break
            else:
                i -= 1
        s['qi']=y_vals[i]
        s['di']=self.default_initial_decline
        s['b']=self.default_b_factor
        s['t0']=x_vals[i]
        s['q0']=y_vals[0] #Probably will need revision, high chance first value is zero
        s['minor_ratio']=minor_ratio
        s['water_ratio']=water_ratio

        return s

    def dca_params(self,s):

        x_vals = s['T_INDEX']

        if s['MAJOR'] == 'OIL':
            y_vals = s['NORMALIZED_OIL']
        elif s['MAJOR'] == 'GAS':
            y_vals = s['NORMALIZED_GAS']
        elif s['MAJOR'] == 'WATER':
            y_vals = s['NORMALIZED_WATER']
        else:
            # Fallback to gas if phase is not recognized
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
            
            if self.verbose:
                print(f'Well {s["UID"]}: After peak detection - {len(filtered_x)} points (from index {indexMin})')

            zero_filter = np.array([y > 0 for y in filtered_y])
            zero_filtered_count = len(filtered_y) - np.sum(zero_filter)
            filtered_x = filtered_x[zero_filter]
            filtered_y = filtered_y[zero_filter]
            
            if self.verbose:
                print(f'Well {s["UID"]}: After zero filtering - {len(filtered_x)} points (removed {zero_filtered_count} zero/negative values)')
            
            outliered_x, outliered_y = self.outlier_detection(filtered_x,filtered_y)
            
            if self.verbose:
                outlier_filtered_count = len(filtered_x) - len(outliered_x)
                print(f'Well {s["UID"]}: After outlier detection - {len(outliered_x)} points (removed {outlier_filtered_count} outliers)')

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
                    bMin = self.min_h_b
                    bMax = self.max_h_b
                else:
                    bMin = self.min_h_b
                    bMax = self.max_h_b

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
                        minor_ratio = np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL_MONTHS:])/np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL_MONTHS:])
                        water_ratio = np.sum(s['NORMALIZED_WATER'][-self.MINOR_TAIL_MONTHS:])/np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL_MONTHS:])
                    else:
                        minor_ratio = np.sum(s['NORMALIZED_OIL'][-self.MINOR_TAIL_MONTHS:])/np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL_MONTHS:])
                        water_ratio = np.sum(s['NORMALIZED_WATER'][-self.MINOR_TAIL_MONTHS:])/np.sum(s['NORMALIZED_GAS'][-self.MINOR_TAIL_MONTHS:])

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

                        if self.backup_decline:
                            return self.handle_dca_error(s,x_vals, y_vals)
                        else:
                            # Return a Series with NaN values for failed DCA
                            s['qi'] = np.nan
                            s['di'] = np.nan
                            s['b'] = np.nan
                            s['t0'] = np.nan
                            s['q0'] = np.nan
                            s['minor_ratio'] = np.nan
                            s['water_ratio'] = np.nan
                except:
                    self.V_DCA_FAILURES += 1
                    if self.verbose:
                        print('DCA Error: '+str(s['UID']), file=self.STAT_FILE, flush=True)

                    if self.backup_decline:
                        return self.handle_dca_error(s,x_vals, y_vals)
                    else:
                        # Return a Series with NaN values for failed DCA
                        s['qi'] = np.nan
                        s['di'] = np.nan
                        s['b'] = np.nan
                        s['t0'] = np.nan
                        s['q0'] = np.nan
                        s['minor_ratio'] = np.nan
                        s['water_ratio'] = np.nan
            else:
                self.V_DCA_FAILURES += 1
                if self.verbose:
                    print(f'Well {s["UID"]}: INSUFFICIENT DATA AFTER FILTERING')
                    print(f'  Original data: {len(x_vals)} points')
                    print(f'  After peak detection: {len(filtered_x)} points')
                    print(f'  After outlier detection: {len(outliered_x)} points')
                    print(f'  Need > 3 points for DCA, but only have {len(outliered_x)}')
                    print('Insufficent data after filtering, well: '+str(s['UID']), file=self.STAT_FILE, flush=True)
                if self.backup_decline:
                    return self.handle_dca_error(s,x_vals, y_vals)
                else:
                    # Return a Series with NaN values for failed DCA
                    s['qi'] = np.nan
                    s['di'] = np.nan
                    s['b'] = np.nan
                    s['t0'] = np.nan
                    s['q0'] = np.nan
                    s['minor_ratio'] = np.nan
                    s['water_ratio'] = np.nan

        else :
            self.V_DCA_FAILURES += 1
            if self.verbose:
                print('Insufficent data before filtering, well: '+str(s['UID']), file=self.STAT_FILE, flush=True)
            if self.backup_decline:
                return self.handle_dca_error(s,x_vals, y_vals)
            else:
                # Return a Series with NaN values for failed DCA
                s['qi'] = np.nan
                s['di'] = np.nan
                s['b'] = np.nan
                s['t0'] = np.nan
                s['q0'] = np.nan
                s['minor_ratio'] = np.nan
                s['water_ratio'] = np.nan

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
                if self.outlier_correction:
                    q3, q2, q1 = np.percentile(l_df['minor_ratio'], [75,50 ,25])
                    high_cutoff = self.iqr_limit*(q3-q1)+q3
                    l_df['minor_ratio'] = np.where(
                        l_df['minor_ratio']>high_cutoff,
                        q2,
                        l_df['minor_ratio']
                    )

                    q3, q2, q1 = np.percentile(l_df['water_ratio'], [75,50 ,25])
                    high_cutoff = self.iqr_limit*(q3-q1)+q3
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
                flow_df['h_length'] / self.STANDARD_LENGTH,
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
                        denormalization_scalar = h_length / self.STANDARD_LENGTH
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
                    flow_df['h_length'] / self.STANDARD_LENGTH,
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
                denormalization_scalar = h_length / self.STANDARD_LENGTH
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
        
        if self.debug_on:
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
        
        if self.debug_on:
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

    def month_diff(self, a, b):
        """Calculate month difference between two datetime series."""
        return 12 * (a.dt.year - b.dt.year) + (a.dt.month - b.dt.month)

    def qi_overwrite(self):
        """
        Calculate 3-month average production rates for initial rate estimation.
        
        This function calculates the average production rates over the last 3 months
        for each well, which can be used to overwrite or validate initial rates.
        Uses the production data already loaded into the decline_curve object.
        
        Returns:
            DataFrame: Contains UID, L3M_OIL, L3M_GAS, L3M_WATER, L3M_START
        """
        if self._dataframe is None:
            raise ValueError("No production data loaded. Set dataframe first.")
            
        # Sort by well and date (descending)
        production_df = self._dataframe.sort_values(by=[self._uid_col, self._date_col], ascending=[True, False])
        
        # Group by well and take the first 3 rows for each group
        top_three_dates = production_df.groupby(self._uid_col).head(3).reset_index()
        
        # Calculate the average value for each well
        result = top_three_dates[[self._uid_col, self._oil_col, self._gas_col, self._water_col, self._date_col]].groupby(self._uid_col).agg({
            self._oil_col: 'mean',
            self._gas_col: 'mean',
            self._water_col: 'mean',
            self._date_col: 'max'
        }).reset_index()
        
        result = result.rename(columns={
            self._uid_col: 'UID',
            self._oil_col: 'L3M_OIL',
            self._gas_col: 'L3M_GAS',
            self._water_col: 'L3M_WATER',
            self._date_col: 'L3M_START'
        })
        
        return result

    def aries_eco_gen(self, oneline_df=None, file_path="outputs/eco_output.txt", scenario="RSC425", dmin=6, write_water=False):
        """
        Generate ARIES-compatible economic forecast file.
        
        This function creates a text file in ARIES format containing production forecasts
        for economic analysis in the ARIES software.
        
        Args:
            oneline_df: Oneline results dataframe (uses self._oneline if None)
            file_path: Output file path
            scenario: Scenario name for ARIES
            dmin: Minimum decline rate
            write_water: Whether to include water production
        """
        if oneline_df is None:
            if self._oneline.empty:
                raise ValueError("No oneline data available. Run generate_oneline() first.")
            oneline_df = self._oneline.copy()
        
        oneline_df = oneline_df.fillna(0)
        
        # Ensure required columns exist and add defaults for missing ones
        # Use T0_DATE if available, otherwise T0, otherwise default
        if 'T0_DATE' in oneline_df.columns:
            oneline_df['T0'] = oneline_df['T0_DATE']
        elif 'T0' not in oneline_df.columns:
            oneline_df['T0'] = pd.Timestamp('2020-01-01')
        if 'DE' not in oneline_df.columns:
            oneline_df['DE'] = 0.1
        if 'B' not in oneline_df.columns:
            oneline_df['B'] = 1.0
        if 'MINOR_RATIO' not in oneline_df.columns:
            oneline_df['MINOR_RATIO'] = 0.0
        if 'WATER_RATIO' not in oneline_df.columns:
            oneline_df['WATER_RATIO'] = 0.0
        if 'L3M_START' not in oneline_df.columns:
            oneline_df['L3M_START'] = pd.Timestamp('2023-12-01')
        if 'L3M_OIL' not in oneline_df.columns:
            oneline_df['L3M_OIL'] = 0.0
        if 'L3M_GAS' not in oneline_df.columns:
            oneline_df['L3M_GAS'] = 0.0
        
        # Calculate revised parameters
        oneline_df['T0'] = pd.to_datetime(oneline_df['T0'])
        oneline_df['revised_dt'] = self.month_diff(oneline_df['L3M_START'], oneline_df['T0'])
        oneline_df['revised_ai'] = oneline_df.apply(lambda x: x['DE']/(1+x['B']*x['DE']*x['revised_dt']), axis=1)
        oneline_df['revised_aries_de'] = oneline_df.apply(lambda x: (1-np.power(((x['revised_ai']*12)*x['B']+1),(-1/x['B'])))*100, axis=1)
        
        # Create output directory if it doesn't exist
        import os
        output_dir = os.path.dirname(file_path)
        if output_dir:  # Only create directory if there is a path
            os.makedirs(output_dir, exist_ok=True)
        
        with open(file_path, "w") as file:
            for index, row in oneline_df.iterrows():
                # Handle both standard mode (MAJOR column) and three-phase mode (phase column)
                major_phase = row.get('MAJOR', row.get('phase', None))
                if major_phase in ['OIL','GAS'] and row['L3M_START'].year > 2020:
                    propnum = str(row['UID']).ljust(93)
                    production = " PRODUCTION".ljust(93)
                    start = "  START".ljust(13) + row['L3M_START'].strftime('%m/%Y')
                    start_padding = " " * (93 - len(start) - len(scenario))
                    start_line = start+start_padding+scenario
                    
                    if major_phase == 'OIL':
                        major_val = round(row['L3M_OIL'],0)
                        major_units = "B/M"
                        minor = "  GAS/OIL".ljust(13) + f"{round(row['MINOR_RATIO'],3)} X M/B TO LIFE LIN TIME"
                        water = "  WTR/OIL".ljust(13) + f"{round(row['WATER_RATIO'],3)} X B/B TO LIFE LIN TIME"
                    else:
                        major_val = round(row['L3M_GAS'],0)
                        major_units = "M/M"
                        minor = "  OIL/GAS".ljust(13) + f"{round(row['MINOR_RATIO'],3)} X B/M TO LIFE LIN TIME"
                        water = "  WTR/GAS".ljust(13) + f"{round(row['WATER_RATIO'],3)} X B/M TO LIFE LIN TIME"
                    
                    # Determine major line based on conditions
                    if row['B']>.01 and row['revised_aries_de'] > dmin and major_val>0:
                        major = f"  {major_phase} ".ljust(13)+f"{major_val} X {major_units} {dmin} EXP B/{round(row['B'],2)} {round(row['revised_aries_de'],2)}"
                        major_padding = " " * (93 - len(major) - len(scenario))
                        major_line = major+major_padding+scenario
                        major_cnt = f'  "'.ljust(13)+f"X X {major_units} 99 YRS EXP {dmin}"
                        major_cnt_padding = " " * (93 - len(major_cnt) - len(scenario))
                        major_cnt_line = major_cnt+major_cnt_padding+scenario
                        
                    elif major_val>0 and row['revised_aries_de'] > dmin:
                        major = f"  {major_phase} ".ljust(13)+f"{major_val} X {major_units} 99 YRS EXP {round(row['revised_aries_de'],2)}"
                        major_padding = " " * (93 - len(major) - len(scenario))
                        major_line = major+major_padding+scenario
                        major_cnt_line = None

                    elif major_val > 0:
                        major = f"  {major_phase} ".ljust(13)+f"{major_val} X {major_units} 99 YRS EXP {dmin}"
                        major_padding = " " * (93 - len(major) - len(scenario))
                        major_line = major+major_padding+scenario
                        major_cnt_line = None

                    else:
                        major = f"  {major_phase} ".ljust(13)+f"{major_val} X {major_units} 1 YRS FLAT 0"
                        major_padding = " " * (93 - len(major) - len(scenario))
                        major_line = major+major_padding+scenario
                        major_cnt_line = None

                    minor_padding = " " * (93 - len(minor) - len(scenario))
                    minor_line = minor+minor_padding+scenario

                    water_padding = " " * (93 - len(water) - len(scenario))
                    water_line = water+water_padding+scenario

                    file.write(propnum + "\n")
                    file.write(production + "\n")
                    file.write(start_line + "\n")
                    file.write(major_line + "\n")
                    if major_cnt_line:
                        file.write(major_cnt_line + "\n")
                    if write_water:
                        file.write(water_line + "\n")

    def aries_eco_gen_three_phase(self, oneline_df=None, file_path="outputs/eco_output.txt", scenario="RSC425", dmin=6, write_water=False):
        """
        Generate ARIES-compatible economic forecast file for three-phase mode.
        
        This function creates a text file in ARIES format containing production forecasts
        for all three phases (OIL, GAS, WATER) with independent decline curves.
        
        Args:
            oneline_df: Oneline results dataframe with phase-specific columns
            file_path: Output file path
            scenario: Scenario name for ARIES
            dmin: Minimum decline rate
            write_water: Whether to include water production
        """
        if oneline_df is None:
            if self._oneline.empty:
                raise ValueError("No oneline data available. Run generate_oneline() first.")
            oneline_df = self._oneline.copy()
        
        oneline_df = oneline_df.fillna(0)
        
        # Ensure required columns exist
        if 'T0_DATE' in oneline_df.columns:
            oneline_df['T0'] = oneline_df['T0_DATE']
        elif 'T0' not in oneline_df.columns:
            oneline_df['T0'] = pd.Timestamp('2020-01-01')
        
        # Create output directory if it doesn't exist
        import os
        output_dir = os.path.dirname(file_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        with open(file_path, "w") as file:
            for index, row in oneline_df.iterrows():
                # Write well header
                propnum = str(row['UID']).ljust(93)
                production = " PRODUCTION".ljust(93)
                start = "  START".ljust(13) + row['T0'].strftime('%m/%Y')
                start_padding = " " * (93 - len(start) - len(scenario))
                start_line = start + start_padding + scenario
                
                file.write(propnum + "\n")
                file.write(production + "\n")
                file.write(start_line + "\n")
                
                # Write OIL phase if it exists
                if row['OIL_QI'] > 0:
                    oil_val = round(row['L3M_OIL'], 0)
                    oil_decline = max(row['OIL_ARIES_DE'], dmin)
                    oil_line = f"  OIL        {oil_val} X B/M {dmin} EXP B/{round(row['OIL_B'], 2)} {round(oil_decline, 2)}"
                    oil_padding = " " * (93 - len(oil_line) - len(scenario))
                    file.write(oil_line + oil_padding + scenario + "\n")
                    
                    # Write continuation line for oil
                    oil_cnt = f'  "          X X B/M 99 YRS EXP {dmin}'
                    oil_cnt_padding = " " * (93 - len(oil_cnt) - len(scenario))
                    file.write(oil_cnt + oil_cnt_padding + scenario + "\n")
                
                # Write GAS phase if it exists
                if row['GAS_QI'] > 0:
                    gas_val = round(row['L3M_GAS'], 0)
                    gas_decline = max(row['GAS_ARIES_DE'], dmin)
                    gas_line = f"  GAS        {gas_val} X M/M {dmin} EXP B/{round(row['GAS_B'], 2)} {round(gas_decline, 2)}"
                    gas_padding = " " * (93 - len(gas_line) - len(scenario))
                    file.write(gas_line + gas_padding + scenario + "\n")
                    
                    # Write continuation line for gas
                    gas_cnt = f'  "          X X M/M 99 YRS EXP {dmin}'
                    gas_cnt_padding = " " * (93 - len(gas_cnt) - len(scenario))
                    file.write(gas_cnt + gas_cnt_padding + scenario + "\n")
                
                # Write WATER phase if it exists and write_water is True
                if write_water and row['WATER_QI'] > 0:
                    water_val = round(row['L3M_WATER'], 0)
                    water_decline = max(row['WATER_ARIES_DE'], dmin)
                    water_line = f"  WATER      {water_val} X M/M {dmin} EXP B/{round(row['WATER_B'], 2)} {round(water_decline, 2)}"
                    water_padding = " " * (93 - len(water_line) - len(scenario))
                    file.write(water_line + water_padding + scenario + "\n")
                    
                    # Write continuation line for water
                    water_cnt = f'  "          X X M/M 99 YRS EXP {dmin}'
                    water_cnt_padding = " " * (93 - len(water_cnt) - len(scenario))
                    file.write(water_cnt + water_cnt_padding + scenario + "\n")

    def generate_aries_export(self, file_path="outputs/eco_output.txt", scenario="RSC425", dmin=6, write_water=False):
        """
        Generate ARIES export with integrated DCA analysis.
        
        This method combines DCA analysis with ARIES export generation.
        When three_phase_mode is enabled, it uses the existing three-phase analysis.
        Otherwise, it creates separate analyses for each phase.
        
        Args:
            file_path: Output file path
            scenario: Scenario name for ARIES
            dmin: Minimum decline rate
            write_water: Whether to include water production
        """
        # Run DCA if not already done
        if self._params_dataframe.empty:
            self.run_DCA()
        
        # Generate oneline if not already done
        if self._oneline.empty:
            self.generate_oneline(denormalize=True)
        
        # Calculate 3-month averages
        l3m_df = self.qi_overwrite()
        
        if self.three_phase_mode:
            # Use existing three-phase analysis
            # The oneline data has separate columns for each phase: IPO/DO/BO, IPG/DG/BG, IPW/DW/BW
            # For ARIES, we need to create a single row per well with all phase data
            # and use the independent decline curves instead of ratios
            
            oneline_with_l3m = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create one row per well with all phase information
            well_rows = []
            for _, row in oneline_with_l3m.iterrows():
                well_row = row.copy()
                
                # Add phase-specific decline parameters
                well_row['OIL_QI'] = row['IPO'] if row['IPO'] > 0 else 0
                well_row['OIL_DI'] = row['DO'] if row['IPO'] > 0 else 0
                well_row['OIL_B'] = row['BO'] if row['IPO'] > 0 else 0
                well_row['OIL_ARIES_DE'] = row['ARIES_DO'] if row['IPO'] > 0 else 0
                
                well_row['GAS_QI'] = row['IPG'] if row['IPG'] > 0 else 0
                well_row['GAS_DI'] = row['DG'] if row['IPG'] > 0 else 0
                well_row['GAS_B'] = row['BG'] if row['IPG'] > 0 else 0
                well_row['GAS_ARIES_DE'] = row['ARIES_DG'] if row['IPG'] > 0 else 0
                
                well_row['WATER_QI'] = row['IPW'] if row['IPW'] > 0 else 0
                well_row['WATER_DI'] = row['DW'] if row['IPW'] > 0 else 0
                well_row['WATER_B'] = row['BW'] if row['IPW'] > 0 else 0
                well_row['WATER_ARIES_DE'] = row['ARIES_DW'] if row['IPW'] > 0 else 0
                
                # Set MAJOR to OIL for compatibility (will be overridden in aries_eco_gen)
                well_row['MAJOR'] = 'OIL'
                
                well_rows.append(well_row)
            
            if well_rows:
                well_df = pd.DataFrame(well_rows)
                # Call aries_eco_gen with three_phase_mode flag
                self.aries_eco_gen_three_phase(well_df, file_path, scenario, dmin, write_water)
            else:
                # Fallback if no valid rows
                print("Warning: No valid phase data found for ARIES export")
                self.aries_eco_gen(oneline_with_l3m, file_path, scenario, dmin, write_water)
        else:
            # Use existing oneline data with ratios (ratio mode)
            # The oneline data already has MINOR_RATIO and WATER_RATIO calculated
            # We just need to use these ratios to calculate gas and water production
            
            oneline_with_l3m = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create one row per well with all phase information using ratios
            well_rows = []
            for _, row in oneline_with_l3m.iterrows():
                well_row = row.copy()
                
                # Primary phase (OIL) - use existing data
                well_row['OIL_QI'] = row['IPO'] if row['IPO'] > 0 else 0
                well_row['OIL_DI'] = row['DE'] if row['IPO'] > 0 else 0  # Use DE for ratio mode
                well_row['OIL_B'] = row['B'] if row['IPO'] > 0 else 0    # Use B for ratio mode
                well_row['OIL_ARIES_DE'] = row['ARIES_DE'] if row['IPO'] > 0 else 0  # Use ARIES_DE for ratio mode
                
                # Gas phase - calculate using MINOR_RATIO
                if row['MINOR_RATIO'] > 0 and row['IPO'] > 0:
                    well_row['GAS_QI'] = row['IPO'] * row['MINOR_RATIO']
                    well_row['GAS_DI'] = row['DE']  # Use same decline as oil
                    well_row['GAS_B'] = row['B']   # Use same b-factor as oil
                    well_row['GAS_ARIES_DE'] = row['ARIES_DE']  # Use same ARIES decline as oil
                else:
                    well_row['GAS_QI'] = 0
                    well_row['GAS_DI'] = 0
                    well_row['GAS_B'] = 0
                    well_row['GAS_ARIES_DE'] = 0
                
                # Water phase - calculate using WATER_RATIO
                if row['WATER_RATIO'] > 0 and row['IPO'] > 0:
                    well_row['WATER_QI'] = row['IPO'] * row['WATER_RATIO']
                    well_row['WATER_DI'] = row['DE']  # Use same decline as oil
                    well_row['WATER_B'] = row['B']   # Use same b-factor as oil
                    well_row['WATER_ARIES_DE'] = row['ARIES_DE']  # Use same ARIES decline as oil
                else:
                    well_row['WATER_QI'] = 0
                    well_row['WATER_DI'] = 0
                    well_row['WATER_B'] = 0
                    well_row['WATER_ARIES_DE'] = 0
                
                # Set MAJOR to OIL for compatibility
                well_row['MAJOR'] = 'OIL'
                
                well_rows.append(well_row)
            
            if well_rows:
                well_df = pd.DataFrame(well_rows)
                # Call aries_eco_gen_three_phase to format with independent decline curves
                self.aries_eco_gen_three_phase(well_df, file_path, scenario, dmin, write_water)
            else:
                # Fallback if no valid rows
                print("Warning: No valid phase data found for ARIES export")
                self.aries_eco_gen(oneline_with_l3m, file_path, scenario, dmin, write_water)
        
        # Note: This function writes to file and does not return a DataFrame

    def generate_mosaic_export(self, file_path="outputs/mosaic_export.xlsx", reserve_category="USON ARO", dmin=8):
        """
        Generate Mosaic-compatible export with integrated DCA analysis.
        
        This method creates a comprehensive export for Mosaic software including
        all phases (OIL, GAS, WATER) with proper formatting and calculations.
        When three_phase_mode is enabled, it uses the existing three-phase analysis.
        Otherwise, it creates separate analyses for each phase.
        
        Args:
            file_path: Output file path (Excel format)
            reserve_category: Reserve category for Mosaic
            dmin: Minimum decline rate
        """
        # Run DCA if not already done
        if self._params_dataframe.empty:
            self.run_DCA()
        
        # Generate oneline if not already done
        if self._oneline.empty:
            self.generate_oneline(denormalize=True)
        
        # Calculate 3-month averages
        l3m_df = self.qi_overwrite()
        
        if self.three_phase_mode:
            # Use existing three-phase analysis
            # The oneline data has separate columns for each phase: IPO/DO/BO, IPG/DG/BG, IPW/DW/BW
            # We need to create separate rows for each phase to match the expected format
            
            # Start with the base oneline data
            base_df = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create separate rows for each phase
            combined_rows = []
            for _, row in base_df.iterrows():
                # OIL phase
                if row['IPO'] > 0:
                    oil_row = row.copy()
                    oil_row['MAJOR'] = 'OIL'
                    oil_row['DE'] = row['DO']
                    oil_row['B'] = row['BO']
                    oil_row['T0'] = row['T0_DATE']
                    combined_rows.append(oil_row)
                
                # GAS phase
                if row['IPG'] > 0:
                    gas_row = row.copy()
                    gas_row['MAJOR'] = 'GAS'
                    gas_row['DE'] = row['DG']
                    gas_row['B'] = row['BG']
                    gas_row['T0'] = row['T0_DATE']
                    combined_rows.append(gas_row)
                
                # WATER phase
                if row['IPW'] > 0:
                    water_row = row.copy()
                    water_row['MAJOR'] = 'WATER'
                    water_row['DE'] = row['DW']
                    water_row['B'] = row['BW']
                    water_row['T0'] = row['T0_DATE']
                    combined_rows.append(water_row)
            
            if combined_rows:
                combined_df = pd.DataFrame(combined_rows)
            else:
                # Fallback if no valid rows
                combined_df = base_df.copy()
                combined_df['MAJOR'] = 'OIL'  # Default
                combined_df['DE'] = 0.1
                combined_df['B'] = 1.0
                combined_df['T0'] = combined_df['T0_DATE']
        else:
            # Use existing oneline data with ratios (ratio mode)
            # The oneline data already has MINOR_RATIO and WATER_RATIO calculated
            # We just need to use these ratios to calculate gas and water production
            
            oneline_with_l3m = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create separate rows for each phase using ratios
            combined_rows = []
            for _, row in oneline_with_l3m.iterrows():
                # OIL phase - use existing data
                if row['IPO'] > 0:
                    oil_row = row.copy()
                    oil_row['MAJOR'] = 'OIL'
                    oil_row['DE'] = row['DE']  # Use DE for ratio mode
                    oil_row['B'] = row['B']    # Use B for ratio mode
                    oil_row['T0'] = row['T0_DATE']
                    oil_row['L3M_OIL'] = row['L3M_OIL']
                    combined_rows.append(oil_row)
                
                # GAS phase - calculate using MINOR_RATIO
                if row['MINOR_RATIO'] > 0 and row['IPO'] > 0:
                    gas_row = row.copy()
                    gas_row['MAJOR'] = 'GAS'
                    gas_row['DE'] = row['DE']  # Use same decline as oil
                    gas_row['B'] = row['B']   # Use same b-factor as oil
                    gas_row['T0'] = row['T0_DATE']
                    gas_row['L3M_GAS'] = row['L3M_OIL'] * row['MINOR_RATIO']  # Calculate gas rate using ratio
                    combined_rows.append(gas_row)
                
                # WATER phase - calculate using WATER_RATIO
                if row['WATER_RATIO'] > 0 and row['IPO'] > 0:
                    water_row = row.copy()
                    water_row['MAJOR'] = 'WATER'
                    water_row['DE'] = row['DE']  # Use same decline as oil
                    water_row['B'] = row['B']   # Use same b-factor as oil
                    water_row['T0'] = row['T0_DATE']
                    water_row['L3M_WATER'] = row['L3M_OIL'] * row['WATER_RATIO']  # Calculate water rate using ratio
                    combined_rows.append(water_row)
            
            if combined_rows:
                combined_df = pd.DataFrame(combined_rows)
            else:
                # Fallback if no valid rows
                print("Warning: No valid phase data found for Mosaic export")
                combined_df = oneline_with_l3m.copy()
                combined_df['MAJOR'] = 'OIL'  # Default
                combined_df['DE'] = 0.1
                combined_df['B'] = 1.0
                combined_df['T0'] = combined_df['T0_DATE']
        
        # Calculate revised parameters
        combined_df = combined_df.fillna(0)
        
        # Ensure T0 column exists and use T0_DATE if available
        if 'T0_DATE' in combined_df.columns:
            combined_df['T0'] = combined_df['T0_DATE']
        elif 'T0' not in combined_df.columns:
            combined_df['T0'] = pd.Timestamp('2020-01-01')
        
        combined_df['T0'] = pd.to_datetime(combined_df['T0'])
        combined_df['revised_dt'] = self.month_diff(combined_df['L3M_START'], combined_df['T0'])
        combined_df['revised_ai'] = combined_df.apply(lambda x: x['DE']/(1+x['B']*x['DE']*x['revised_dt']), axis=1)
        combined_df['revised_aries_de'] = combined_df.apply(lambda x: (1-np.power(((x['revised_ai']*12)*x['B']+1),(-1/x['B'])))*100, axis=1)
        
        # Calculate used IP based on major phase
        combined_df['used_ip'] = combined_df.apply(lambda row: row[f"L3M_{row['MAJOR']}"], axis=1)
        
        # Format for Mosaic
        output_df = combined_df.rename(columns={
            'UID': 'Entity Name',
            'used_ip': 'Initial Rate qi (rate/d)',
            'B': 'Exponent N, b',
            'revised_aries_de': 'Secant Effective Decline Desi (%)',
            'L3M_START': 'Start Date T0  (y-m-d)',
            'MAJOR': 'Product Type'
        })
        
        # Add required columns
        add_list = [
            'UUID', 'Reserve Category', 'Use Type', 'Segment #', 'Final Rate qf (rate/d)',
            'D Cum', 'Final Cum', 'Length DT (years)', 'Final Date Tf  (y-m-d)',
            'Nominal Decline Di (%)', 'Tangential Effective Decline   Dei (%)',
            'Service Factor (fraction)', 'Minimum Effective Decline Dmin (%)'
        ]
        
        for col in add_list:
            output_df[col] = None
        
        # Set default values
        output_df['Reserve Category'] = reserve_category
        output_df['Use Type'] = 'Produced'
        output_df['Segment #'] = 1
        output_df['Length DT (years)'] = 100
        output_df['Minimum Effective Decline Dmin (%)'] = dmin
        output_df['Product Type'] = output_df['Product Type'].str.capitalize()
        output_df['Initial Rate qi (rate/d)'] = output_df['Initial Rate qi (rate/d)'] * 12 / 365
        
        # Ensure minimum decline rate
        output_df['Secant Effective Decline Desi (%)'] = np.where(
            output_df['Secant Effective Decline Desi (%)'] < dmin,
            dmin,
            output_df['Secant Effective Decline Desi (%)']
        )
        
        # Select final columns
        final_columns = [
            'Entity Name', 'UUID', 'Reserve Category', 'Product Type', 'Use Type', 'Segment #',
            'Start Date T0  (y-m-d)', 'Initial Rate qi (rate/d)', 'Final Rate qf (rate/d)',
            'D Cum', 'Final Cum', 'Length DT (years)', 'Final Date Tf  (y-m-d)',
            'Exponent N, b', 'Nominal Decline Di (%)', 'Tangential Effective Decline   Dei (%)',
            'Secant Effective Decline Desi (%)', 'Service Factor (fraction)',
            'Minimum Effective Decline Dmin (%)'
        ]
        
        output_df = output_df[final_columns]
        
        # Create output directory if it doesn't exist
        import os
        output_dir = os.path.dirname(file_path)
        if output_dir:  # Only create directory if there is a path
            os.makedirs(output_dir, exist_ok=True)
        
        # Save to Excel
        output_df.to_excel(file_path, index=False)
        
        # Note: This function writes to file and does not return a DataFrame

    def generate_phdwin_export(self, file_path="outputs/phdwin_export.csv", dmin=6):
        """
        Generate PhdWin-compatible export with integrated DCA analysis.
        
        This method creates a comprehensive export for PhdWin software including
        all phases (OIL, GAS, WATER) with proper formatting and calculations.
        When three_phase_mode is enabled, it uses the existing three-phase analysis.
        Otherwise, it creates separate analyses for each phase.
        
        Args:
            file_path: Output file path (CSV format)
            dmin: Minimum decline rate
        """
        # Run DCA if not already done
        if self._params_dataframe.empty:
            # Set parameters to match reference script
            self.D_MIN = 0.06/12
            self.backup_decline = False
            self.OUTLIER_CORRECTION = False
            self.min_h_b = 0.01
            self.max_h_b = 1.3
            self.run_DCA()
        
        # Generate oneline if not already done
        if self._oneline.empty:
            self.generate_oneline(denormalize=True)
        
        # Calculate 3-month averages
        l3m_df = self.qi_overwrite()
        
        if self.three_phase_mode:
            # Use existing three-phase analysis
            # The oneline data has separate columns for each phase: IPO/DO/BO, IPG/DG/BG, IPW/DW/BW
            
            # Start with the base oneline data
            base_df = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create separate rows for each phase
            combined_rows = []
            for _, row in base_df.iterrows():
                # OIL phase - use existing data
                if row['IPO'] > 0:
                    oil_row = row.copy()
                    oil_row['MAJOR'] = 'OIL'
                    oil_row['revised_qi'] = row['L3M_OIL']
                    oil_row['DE'] = row['DO']  # Use DO (Decline Oil)
                    oil_row['B'] = row['BO']   # Use BO (B-factor Oil)
                    oil_row['T0'] = row['T0_DATE']
                    combined_rows.append(oil_row)
                
                # GAS phase - use gas production data and gas-specific decline parameters
                if row['IPG'] > 0:
                    gas_row = row.copy()
                    gas_row['MAJOR'] = 'GAS'
                    gas_row['revised_qi'] = row['L3M_GAS']
                    gas_row['DE'] = row['DG']  # Use DG (Decline Gas)
                    gas_row['B'] = row['BG']   # Use BG (B-factor Gas)
                    gas_row['T0'] = row['T0_DATE']
                    combined_rows.append(gas_row)
                
                # WATER phase - use water production data and water-specific decline parameters
                if row['IPW'] > 0:  # Check if water production exists
                    water_row = row.copy()
                    water_row['MAJOR'] = 'WATER'
                    water_row['revised_qi'] = row['L3M_WATER']
                    water_row['DE'] = row['DW']  # Use DW (Decline Water)
                    water_row['B'] = row['BW']   # Use BW (B-factor Water)
                    water_row['T0'] = row['T0_DATE']
                    combined_rows.append(water_row)
            
            if combined_rows:
                tc_df = pd.DataFrame(combined_rows)
            else:
                # Fallback if no valid rows
                tc_df = base_df.copy()
                tc_df['MAJOR'] = 'OIL'  # Default
                tc_df['revised_qi'] = tc_df['L3M_OIL']
                tc_df['DE'] = 0.1
                tc_df['B'] = 1.0
                tc_df['T0'] = tc_df['T0_DATE']
        else:
            # Use existing oneline data with ratios (ratio mode)
            # The oneline data already has MINOR_RATIO and WATER_RATIO calculated
            # We just need to use these ratios to calculate gas and water production
            
            oneline_with_l3m = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create separate rows for each phase using ratios
            combined_rows = []
            for _, row in oneline_with_l3m.iterrows():
                # OIL phase - use existing data
                if row['IPO'] > 0:
                    oil_row = row.copy()
                    oil_row['MAJOR'] = 'OIL'
                    oil_row['DE'] = row['DE']  # Use DE for ratio mode
                    oil_row['B'] = row['B']    # Use B for ratio mode
                    oil_row['T0'] = row['T0_DATE']
                    oil_row['L3M_OIL'] = row['L3M_OIL']
                    combined_rows.append(oil_row)
                
                # GAS phase - calculate using MINOR_RATIO
                if row['MINOR_RATIO'] > 0 and row['IPO'] > 0:
                    gas_row = row.copy()
                    gas_row['MAJOR'] = 'GAS'
                    gas_row['DE'] = row['DE']  # Use same decline as oil
                    gas_row['B'] = row['B']   # Use same b-factor as oil
                    gas_row['T0'] = row['T0_DATE']
                    gas_row['L3M_GAS'] = row['L3M_OIL'] * row['MINOR_RATIO']  # Calculate gas rate using ratio
                    combined_rows.append(gas_row)
                
                # WATER phase - calculate using WATER_RATIO
                if row['WATER_RATIO'] > 0 and row['IPO'] > 0:
                    water_row = row.copy()
                    water_row['MAJOR'] = 'WATER'
                    water_row['DE'] = row['DE']  # Use same decline as oil
                    water_row['B'] = row['B']   # Use same b-factor as oil
                    water_row['T0'] = row['T0_DATE']
                    water_row['L3M_WATER'] = row['L3M_OIL'] * row['WATER_RATIO']  # Calculate water rate using ratio
                    combined_rows.append(water_row)
            
            if combined_rows:
                tc_df = pd.DataFrame(combined_rows)
            else:
                # Fallback if no valid rows
                print("Warning: No valid phase data found for PhdWin export")
                tc_df = oneline_with_l3m.copy()
                tc_df['MAJOR'] = 'OIL'  # Default
                tc_df['DE'] = 0.1
                tc_df['B'] = 1.0
                tc_df['T0'] = tc_df['T0_DATE']
        
        # Calculate revised parameters
        # Use T0 from oneline data (matching reference script approach)
        tc_df['T0'] = tc_df['T0_DATE']
        
        tc_df['revised_dt'] = self.month_diff(tc_df['L3M_START'], tc_df['T0'])
        
        # QI Revisions
        tc_df['revised_qi'] = np.where(
            tc_df['MAJOR'] == 'OIL',
            tc_df['L3M_OIL'] * np.power((1 + tc_df['B'] * tc_df['DE'] * tc_df['revised_dt']), 1 / tc_df['B']),
            np.where(
                tc_df['MAJOR'] == 'GAS',
                tc_df['L3M_GAS'] * np.power((1 + tc_df['B'] * tc_df['DE'] * tc_df['revised_dt']), 1 / tc_df['B']),
                np.where(
                    tc_df['MAJOR'] == 'WATER',
                    tc_df['L3M_WATER'] * np.power((1 + tc_df['B'] * tc_df['DE'] * tc_df['revised_dt']), 1 / tc_df['B']),
                    0
                )
            )
        )
        
        # Adjust the ARIES_DE column to actually be the PhdWin De
        tc_df['ARIES_DE'] = tc_df.apply(lambda x: 100*(1-np.exp(-x['DE']*12)), axis=1)
        
        # Format for PhdWin
        output_columns = [
            'UniqueId', 'Product', 'Units', 'ProjType', 'StartDate', 'BegCum',
            'Qi', 'NFactor', 'Decl', 'DeclMin', 'EndDate', 'Qf', 'Volume',
            'EndCum', 'SolveFor'
        ]
        
        output_df = tc_df.copy()
        
        # Set end date (50 years forward) - match reference script
        fifty_years_forward = pd.Timestamp('2075-01-01')
        
        output_df['UniqueId'] = output_df['UID']
        output_df['Product'] = output_df['MAJOR'].str.title()
        output_df['Units'] = np.where(output_df['Product'] == 'Gas', 'Mcf', 'bbl')
        output_df['ProjType'] = 'Arps'
        output_df['StartDate'] = output_df['T0']
        output_df['BegCum'] = 0
        output_df['Qi'] = output_df['revised_qi']
        output_df['NFactor'] = np.where(output_df['B'] > 0.01, output_df['B'], 0)
        output_df['Decl'] = np.where(
            output_df['ARIES_DE'] > 2,
            output_df['ARIES_DE'],
            np.where(output_df['ARIES_DE'] > 0, 2, 0)
        )
        output_df['DeclMin'] = np.where(
            (output_df['NFactor'] > 0.01) & (output_df['ARIES_DE'] > 6),
            6,
            np.where((output_df['NFactor'] > 0.01), 2, 0)
        )
        output_df['Qf'] = None
        output_df['Volume'] = None
        output_df['EndCum'] = None
        output_df['SolveFor'] = np.where(
            output_df['Product'].isin(["Oil", 'Gas', 'Water']),
            'Qf;Vol',
            'Qf'
        )
        output_df['EndDate'] = fifty_years_forward
        
        output_df = output_df[output_columns]
        
        # Create output directory if it doesn't exist
        import os
        output_dir = os.path.dirname(file_path)
        if output_dir:  # Only create directory if there is a path
            os.makedirs(output_dir, exist_ok=True)
        
        # Save to CSV
        output_df.to_csv(file_path, index=False)
        
        # Note: This function writes to file and does not return a DataFrame

    def make_ratio_dfs(self, input_df=None):
        """
        Create ratio dataframes for PhdWin-style analysis.
        
        This function creates separate dataframes for different production ratios
        (GOR, yield, WOR, WGR) that can be used for specialized analysis.
        
        Args:
            input_df: Input dataframe with L3M data (uses qi_overwrite result if None)
            
        Returns:
            DataFrame: Combined ratio dataframes
        """
        if input_df is None:
            input_df = self.qi_overwrite()
        
        # Function to calculate T0 (3 months before L3M_START)
        def calculate_t0(l3m_start):
            if pd.notnull(l3m_start):
                return (l3m_start - pd.DateOffset(months=3)).replace(day=1)
            return pd.NaT

        # Create and populate the new DataFrames
        ratios = {
            "gor_df": lambda row: (row["L3M_GAS"] / row["L3M_OIL"])*1000 if row["L3M_OIL"] else 0,
            "yield_df": lambda row: (row["L3M_OIL"] / row["L3M_GAS"])*1000 if row["L3M_GAS"] else 0,
            "wor_df": lambda row: row["L3M_WATER"] / row["L3M_OIL"] if row["L3M_OIL"] else 0,
            "wgr_df": lambda row: (row["L3M_WATER"] / row["L3M_GAS"])*1000 if row["L3M_GAS"] else 0,
        }

        final_df = pd.DataFrame([])

        for key, func in ratios.items():
            new_df = input_df[["UID", "L3M_OIL", "L3M_GAS", "L3M_WATER", "L3M_START"]].copy()
            new_df["T0"] = new_df["L3M_START"].apply(calculate_t0)
            new_df["revised_qi"] = input_df.apply(func, axis=1).fillna(0)
            new_df["MAJOR"] = key.split("_")[0].upper()
            # Add remaining blank columns
            for col in ["OIL", "GAS", "WATER", "IPO", "IPG", "B", "DE", "MINOR_RATIO", "WATER_RATIO", "ARIES_DE", "revised_dt"]:
                new_df[col] = None
            if final_df.empty:
                final_df = new_df
            else:
                final_df = pd.concat([final_df,new_df])

        final_df = final_df[[
            'UID',
            'OIL',
            'GAS',
            'WATER',
            'MAJOR',
            'IPO',
            'IPG',
            'B',
            'DE',
            'T0',
            'MINOR_RATIO',
            'WATER_RATIO',
            'ARIES_DE',
            'L3M_OIL',
            'L3M_GAS',
            'L3M_START',
            'revised_dt',
            'revised_qi'
        ]]
        
        return final_df


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
