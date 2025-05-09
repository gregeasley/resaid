import pandas as pd
import numpy as np
import sys
from scipy.optimize import newton
from tqdm import tqdm

class npv_calc():
    
    def __init__(self,cashflow:np.array):
        self._cashflow = cashflow

    def constraint(self,x):
        return x


    def get_npv(self,discount_rate):
        #if np.sum(self._cashflow) < 0:
        #    l_npv = -1
        #elif discount_rate < 0:
        #    l_npv = 99999
        #else:
        l_npv = np.sum(self._cashflow/ (1+discount_rate)**np.arange(0, len(self._cashflow)))

        return l_npv
    
    def get_irr(self, iterations=50):
        guess = .1/12

        constraint_bounds = ((1e-6, .16),) 

        if np.sum(self._cashflow) < 0:
            result = 0
        else:
            result = newton(self.get_npv, guess, maxiter=iterations)

        try:
            result = 12*result
        except Exception as e:
            print(result)
            raise e

        return result

class well_econ:

    def __init__(self,verbose=False):
        #Constants
        self.STAT_FILE = sys.stdout
        self.OIL_COL = "OIL"
        self.GAS_COL = 'GAS'
        self.WATER_COL = 'WATER'

        self._verbose = verbose

        #Settable
        self._flowstreams = None
        self._header_data = None

        self._flowstream_uwi_col = None
        self._flowstream_t_index = None
        self._header_uwi_col = None

        self._royalty = None

        self._opc_t = None
        self._opc_oil = None
        self._opc_gas = None
        self._opc_water = None

        self._scale_capex = False
        self._scale_column = None
        self._capex_val = None
        self._capex_col = None # Careful, will override any prior settings

        self._atx = None
        self._sev_gas = None
        self._sev_oil = None

        self._oil_pri = None
        self._gas_pri = None
        
        self._discount_rate = None

        self._breakeven_phase = None

        # optional variables
        self._royalty_col = None
        self._owned_royalty_col = None

        self._wi_col = None
        self._nri_col = None

        self._gas_shrink = 0 
        self._ngl_yield = 0 # input as b/M post shrink
        self._ngl_price_fraction = 0
        self._scale_forecast = False
        self._scale_base = 5280
        self._oil_diff = 0
        self._gas_diff = 0

        self._spud_to_online = None
        self._t_start_column = None

        #Get only
        self._indicators = None

    @property
    def nri_col(self):
        return self._nri_col


    @nri_col.setter
    def nri_col(self,value):
        self._nri_col = value

    @property
    def wi_col(self):
        return self._wi_col


    @wi_col.setter
    def wi_col(self,value):
        self._wi_col = value

    @property
    def capex_col(self):
        return self._capex_col


    @capex_col.setter
    def capex_col(self,value):
        self._capex_col = value

    @property
    def gas_diff(self):
        return self._gas_diff


    @gas_diff.setter
    def gas_diff(self,value):
        self._gas_diff = value

    @property
    def oil_diff(self):
        return self._oil_diff


    @oil_diff.setter
    def oil_diff(self,value):
        self._oil_diff = value

    @property
    def t_start_column(self):
        return self._t_start_column


    @t_start_column.setter
    def t_start_column(self,value):
        self._t_start_column = value

    @property
    def scale_forecast(self):
        return self._scale_forecast


    @scale_forecast.setter
    def scale_forecast(self,value):
        self._scale_forecast = value

    @property
    def spud_to_online(self):
        return self._spud_to_online


    @spud_to_online.setter
    def spud_to_online(self,value):
        self._spud_to_online = value

    @property
    def ngl_price_fraction(self):
        return self._ngl_price_fraction


    @ngl_price_fraction.setter
    def ngl_price_fraction(self,value):
        self._ngl_price_fraction = value

    @property
    def ngl_yield(self):
        return self._ngl_yield


    @ngl_yield.setter
    def ngl_yield(self,value):
        self._ngl_yield = value

    @property
    def gas_shrink(self):
        return self._gas_shrink


    @gas_shrink.setter
    def gas_shrink(self,value):
        self._gas_shrink = value

    @property
    def gas_shrink(self):
        return self._gas_shrink


    @gas_shrink.setter
    def gas_shrink(self,value):
        self._gas_shrink = value

    @property
    def royalty_col(self):
        return self._royalty_col


    @royalty_col.setter
    def royalty_col(self,value):
        self._royalty_col = value
        
    @property
    def owned_royalty_col(self):
        return self._owned_royalty_col


    @owned_royalty_col.setter
    def owned_royalty_col(self,value):
        self._owned_royalty_col = value

    @property
    def flowstreams(self):
        return self._flowstreams


    @flowstreams.setter
    def flowstreams(self,value):
        self._flowstreams = value

    @property
    def flowstream_uwi_col(self):
        return self._flowstream_uwi_col


    @flowstream_uwi_col.setter
    def flowstream_uwi_col(self,value):
        self._flowstream_uwi_col = value

    @property
    def flowstream_t_index(self):
        return self._flowstream_t_index


    @flowstream_t_index.setter
    def flowstream_t_index(self,value):
        self._flowstream_t_index = value

    @property
    def header_uwi_col(self):
        return self._header_uwi_col


    @header_uwi_col.setter
    def header_uwi_col(self,value):
        self._header_uwi_col = value

    @property
    def header_data(self):
        return self._header_data


    @header_data.setter
    def header_data(self,value):
        self._header_data = value

    @property
    def royalty(self):
        return self._royalty


    @royalty.setter
    def royalty(self,value):
        self._royalty = value

    @property
    def opc_t(self):
        return self._opc_t


    @opc_t.setter
    def opc_t(self,value):
        self._opc_t = value

    @property
    def opc_oil(self):
        return self._opc_oil


    @opc_oil.setter
    def opc_oil(self,value):
        self._opc_oil = value

    @property
    def opc_gas(self):
        return self._opc_gas


    @opc_gas.setter
    def opc_gas(self,value):
        self._opc_gas = value

    @property
    def opc_water(self):
        return self._opc_water


    @opc_water.setter
    def opc_water(self,value):
        self._opc_water = value

    @property
    def scale_capex(self):
        return self._scale_capex


    @scale_capex.setter
    def scale_capex(self,value):
        self._scale_capex = value

    @property
    def scale_column(self):
        return self._scale_column


    @scale_column.setter
    def scale_column(self,value):
        self._scale_column = value

    @property
    def capex_val(self):
        return self._capex_val


    @capex_val.setter
    def capex_val(self,value):
        self._capex_val = value

    @property
    def atx(self):
        return self._atx


    @atx.setter
    def atx(self,value):
        self._atx = value

    @property
    def sev_gas(self):
        return self._sev_gas


    @sev_gas.setter
    def sev_gas(self,value):
        self._sev_gas = value

    @property
    def sev_oil(self):
        return self._sev_oil


    @sev_oil.setter
    def sev_oil(self,value):
        self._sev_oil = value

    @property
    def oil_pri(self):
        return self._oil_pri


    @oil_pri.setter
    def oil_pri(self,value):
        self._oil_pri = value

    @property
    def gas_pri(self):
        return self._gas_pri


    @gas_pri.setter
    def gas_pri(self,value):
        self._gas_pri = value

    @property
    def discount_rate(self):
        return self._discount_rate


    @discount_rate.setter
    def discount_rate(self,value):
        self._discount_rate = value

    @property
    def indicators(self):
        return self._indicators

    @property
    def breakeven_phase(self):
        return self._breakeven_phase

    @breakeven_phase.setter
    def breakeven_phase(self,value):
        self._breakeven_phase = value

   

    def generate_oil_price(self,times):
        oil_price = []
        if isinstance(self._oil_pri, list):
            if len(self._oil_pri) >= len(times):
                oil_price = self._oil_pri[0:len(times)]
            else:
                last_pri = self._oil_pri[-1]
                num_to_add = len(times)-len(self._oil_pri)
                add_list = [last_pri for i in range(num_to_add)]
                oil_price = self._oil_pri
                oil_price.extend(add_list)
        else:
            oil_price = [self._oil_pri for i in range(len(times))]

        return np.array(oil_price)+self.oil_diff

    def generate_gas_price(self,times):
        gas_price = []
        if isinstance(self._gas_pri, list):
            if len(self._gas_pri) >= len(times):
                gas_price = self._gas_pri[0:len(times)]
            else:
                last_pri = self._gas_pri[-1]
                num_to_add = len(times)-len(self._gas_pri)
                add_list = [last_pri for i in range(num_to_add)]
                gas_price = self._gas_pri
                gas_price.extend(add_list)
        else:
            gas_price = [self._gas_pri for i in range(len(times))]

        return np.array(gas_price)+self.gas_diff

    def generate_capex(self,times,well):
        l_capex = np.zeros(times)

        if self._t_start_column:
            #capex_point = self._header_data[self._header_data[self._header_uwi_col]==well].iloc[0][self._t_start_column]
            capex_point=0
        else:
            capex_point=0

        if self._capex_col:
            capex_val = self._header_data[self._header_data[self._header_uwi_col]==well].iloc[0][self._capex_col]
            l_capex[capex_point] = capex_val

        elif self._scale_capex:

            scale_val = self._header_data[self._header_data[self._header_uwi_col]==well].iloc[0][self._scale_column]

            l_capex[capex_point] = self.capex_val*scale_val
        else:
            l_capex[capex_point] = self._capex_val

        return l_capex

    def zero_below(self,df:pd.DataFrame,i_max:int, cols:list):
        for col in cols:
            df[col] = np.where(
                df['T_INDEX'] <= i_max,
                df[col],
                0
            )

        return df

    def well_flowstream(self,input_well):

        l_flow = self._flowstreams[self._flowstreams[self._flowstream_uwi_col]==input_well].reset_index(drop=True)

        if self._scale_forecast:
            scale_val = self._header_data[self._header_data[self._header_uwi_col]==input_well].iloc[0][self._scale_column]
            l_flow[self.OIL_COL] = l_flow[self.OIL_COL]*scale_val/self._scale_base
            l_flow[self.GAS_COL] = l_flow[self.GAS_COL]*scale_val/self._scale_base

        if self._t_start_column:
            start_val = self._header_data[self._header_data[self._header_uwi_col]==input_well].iloc[0][self._t_start_column]
            l_uid = l_flow[self._flowstream_uwi_col].iloc[0]
            l_major = l_flow['MAJOR'].iloc[0]
            l_t_index = pd.Series(range(1,start_val+1,1))

            # Create a DataFrame of zeros
            start_df = pd.DataFrame(0, index=range(start_val), columns=l_flow.columns)
            start_df[self._flowstream_uwi_col] = l_uid
            start_df['MAJOR'] = l_major
            start_df[self._flowstream_t_index] = l_t_index

            # Concatenate the zeros DataFrame with the original DataFrame
            l_flow[self._flowstream_t_index] += start_val
            #l_flow = pd.concat([zeros_df, l_flow]).reset_index(drop=True)
        else:
            start_val = 0
            start_df = pd.DataFrame([])
        
        if self._spud_to_online:
            n = self._spud_to_online  # Number of rows to insert

            l_uid = l_flow[self._flowstream_uwi_col].iloc[0]
            l_major = l_flow['MAJOR'].iloc[0]
            l_t_index = pd.Series(range(start_val+1,start_val+n+1,1))

            # Create a DataFrame of zeros
            zeros_df = pd.DataFrame(0, index=range(n), columns=l_flow.columns)
            zeros_df[self._flowstream_uwi_col] = l_uid
            zeros_df['MAJOR'] = l_major
            zeros_df[self._flowstream_t_index] = l_t_index

            if not start_df.empty:
                zeros_df = pd.concat([start_df,zeros_df])

            # Concatenate the zeros DataFrame with the original DataFrame
            l_flow[self._flowstream_t_index] += n
            l_flow = pd.concat([zeros_df, l_flow]).reset_index(drop=True)
        else:
            n = 0

        
        l_flow['gas_sold'] = l_flow[self.GAS_COL]*(1-self._gas_shrink)
        l_flow['ngl_volume'] = l_flow['gas_sold']*self._ngl_yield
        t_series = np.array(range(len(l_flow)))

        l_flow['oil_price'] = self.generate_oil_price(t_series)
        l_flow['gas_price'] = self.generate_gas_price(t_series)
        l_flow['ngl_price'] = l_flow['oil_price'] * self._ngl_price_fraction

        l_flow['oil_revenue'] = l_flow[self.OIL_COL]*l_flow['oil_price']
        l_flow['gas_revenue'] = l_flow['gas_sold']*l_flow['gas_price']
        l_flow['ngl_revenue'] = l_flow['ngl_volume']*l_flow['ngl_price']

        l_flow['revenue'] = (
            l_flow[self.OIL_COL]*l_flow['oil_price']
            +l_flow['gas_sold']*l_flow['gas_price']
            +l_flow['ngl_volume']*l_flow['ngl_price']
        )

        
        if self._wi_col and self._nri_col and self._owned_royalty_col and self._royalty_col:
            l_nri = self._header_data[self._header_data[self._header_uwi_col]==input_well].iloc[0][self._nri_col]
            l_wi = self._header_data[self._header_data[self._header_uwi_col]==input_well].iloc[0][self._wi_col]
            l_ori = self._header_data[self._header_data[self._header_uwi_col]==input_well].iloc[0][self._owned_royalty_col]
            l_royalty = self._header_data[self._header_data[self._header_uwi_col]==input_well].iloc[0][self._royalty_col]
            if l_nri+l_royalty>1:
                raise Exception(ValueError, f"Sum of royalty and NRI must be less than or equal to 1, currently {l_nri+l_royalty}")
            l_flow['royalty'] = l_flow['revenue']*l_royalty
            
        elif self._wi_col and self._nri_col:  
            l_nri = self._header_data[self._header_data[self._header_uwi_col]==input_well].iloc[0][self._nri_col]
            l_wi = self._header_data[self._header_data[self._header_uwi_col]==input_well].iloc[0][self._wi_col]
            l_ori = 0
            l_royalty = 1-l_nri/l_wi
            l_flow['royalty'] = l_flow['revenue']*l_royalty
        elif self._royalty_col:
            l_royalty = self._header_data[self._header_data[self._header_uwi_col]==input_well].iloc[0][self._royalty_col]
            l_ori = 0
            l_flow['royalty'] = l_flow['revenue']*l_royalty
            l_wi = 1
            l_nri = 1-l_royalty
        else:
            l_royalty = self._royalty
            l_flow['royalty'] = l_flow['revenue']*self._royalty
            l_wi = 1
            l_nri = 1-l_royalty

        l_flow['fixed_expense'] = self._opc_t
        l_flow['oil_variable_expense'] = self._opc_oil*l_flow[self.OIL_COL]
        l_flow['gas_variable_expense'] = self._opc_gas*l_flow['gas_sold']
        l_flow['water_variable_expense'] = self._opc_water*l_flow[self.WATER_COL]

        l_flow['expense'] = (
            self._opc_t
            + self._opc_gas*l_flow['gas_sold']
            + self._opc_oil*l_flow[self.OIL_COL]
            + self._opc_water*l_flow[self.WATER_COL]
        )

        l_flow['expense'] = np.where(
            l_flow[self._flowstream_t_index] < start_val+n,
            0,
            l_flow['expense']
        )

        l_flow['severance_tax'] = (
            self._sev_gas*l_flow[self.GAS_COL]*l_flow['gas_price']
            + self._sev_oil*l_flow[self.OIL_COL]*l_flow['oil_price']
        )*(1-l_royalty)

        l_flow['ad_val_tax'] = self._atx*l_flow['revenue']*(1-l_royalty)

        l_flow['taxes'] = (
            self._atx*l_flow['revenue']
            + self._sev_gas*l_flow[self.GAS_COL]*l_flow['gas_price']
            + self._sev_oil*l_flow[self.OIL_COL]*l_flow['oil_price']
        )*(1-l_royalty)

        l_flow['capex'] = self.generate_capex(len(l_flow),input_well)

        l_flow['cf'] = (
            l_flow['revenue']
            - l_flow['royalty']
            - l_flow['expense']
            - l_flow['taxes']
            - l_flow['capex']
        )


        l_flow['dcf'] = (l_flow['cf'].to_numpy() / (1+self._discount_rate)**np.arange(0, len(l_flow['cf'].to_numpy())))
        

        try:
            cf_idx = np.argwhere(l_flow['dcf'].to_numpy()>0)
        except:
            cf_idx=[]

        if len(cf_idx) > 0:
            last_cf = np.max(np.argwhere(l_flow['dcf'].to_numpy()>0))
        else:
            last_cf = 0

        zero_cols = [
            self.OIL_COL,
            self.GAS_COL,
            'gas_sold',
            self.WATER_COL,
            'ngl_volume',
            'oil_revenue',
            'gas_revenue',
            'ngl_revenue',
            'revenue',
            'royalty',
            'fixed_expense',
            'oil_variable_expense',
            'gas_variable_expense',
            'water_variable_expense',
            'expense',
            'severance_tax',
            'ad_val_tax',
            'taxes',
            'capex',
            'cf',
            'dcf'
        ]

        l_flow = self.zero_below(l_flow,last_cf,zero_cols)

        # calculate WI vales
        l_flow[['wi_oil',
            'wi_gas',
            'wi_ngl',
            'wi_revenue',
            'wi_royalty',
            'wi_expense',
            'wi_severance_tax',
            'wi_ad_val_tax',
            'wi_taxes',
            'wi_capex',
            'wi_cf',
            'wi_dcf']] = l_flow[[self.OIL_COL,
            'gas_sold',
            'ngl_volume',
            'revenue',
            'royalty',
            'expense',
            'severance_tax',
            'ad_val_tax',
            'taxes',
            'capex',
            'cf',
            'dcf']].mul(l_wi)
        
        l_flow['net_oil'] = l_flow[self.OIL_COL]*(l_nri+l_royalty*l_ori)
        l_flow['net_gas'] = l_flow['gas_sold']*(l_nri+l_royalty*l_ori)
        l_flow['net_ngl'] = l_flow['ngl_volume']*(l_nri+l_royalty*l_ori)
        l_flow['net_oil_revenue'] = l_flow['oil_revenue']*(l_nri+l_royalty*l_ori)
        l_flow['net_gas_revenue'] = l_flow['gas_revenue']*(l_nri+l_royalty*l_ori)
        l_flow['net_ngl_revenue'] = l_flow['ngl_revenue']*(l_nri+l_royalty*l_ori)
        l_flow['net_revenue'] = l_flow['revenue']*(l_nri+l_royalty*l_ori)
        l_flow['net_royalty'] = 0
        l_flow['net_expense'] = l_flow['wi_expense']
        l_flow['net_severance_tax'] = l_flow['severance_tax']/(1-l_royalty)*(l_nri+l_royalty*l_ori)
        l_flow['net_ad_val_tax'] = l_flow['ad_val_tax']/(1-l_royalty)*(l_nri+l_royalty*l_ori)
        l_flow['net_taxes'] = l_flow['taxes']/(1-l_royalty)*(l_nri+l_royalty*l_ori)
        l_flow['net_capex'] = l_flow['wi_capex']
        l_flow['net_cf'] = (
            l_flow['net_revenue']
            - l_flow['net_royalty']
            - l_flow['net_expense']
            - l_flow['net_taxes']
            - l_flow['net_capex']
        )
        l_flow['net_dcf'] = (l_flow['net_cf'].to_numpy() / (1+self._discount_rate)**np.arange(0, len(l_flow['cf'].to_numpy())))

        l_flow['wi_net_oil'] = l_flow[self.OIL_COL]*(l_nri+l_royalty*l_ori)
        l_flow['wi_net_gas'] = l_flow['gas_sold']*(l_nri+l_royalty*l_ori)
        l_flow['wi_net_ngl'] = l_flow['ngl_volume']*(l_nri+l_royalty*l_ori)

        return l_flow


    def generate_indicators(self):

        ind_dict = {
            'UWI':[],
            'EURO':[],
            'EURG':[],
            'EURW':[],
            'REVENUE':[],
            'ROYALTY':[],
            'OPEX':[],
            'TAXES':[],
            'CAPEX':[],
            'FCF':[],
            'DCF':[],
            'IRR':[],
            'ROI':[],
            'PAYOUT':[],
            'BREAKEVEN':[],
            'BREAKEVEN_PHASE':[]
        }

        unique_wells = self._flowstreams[self._flowstream_uwi_col].unique()

        iterable = tqdm(unique_wells) if self._verbose else unique_wells

        for w in iterable:
            
            l_flow = self.well_flowstream(w)
            #l_flow.to_csv(f'tests/{w}.csv')
            
            dc_rev = (l_flow['revenue'].to_numpy() / (1+self._discount_rate)**np.arange(0, len(l_flow['revenue'].to_numpy())))

            if self._breakeven_phase is None:
                if np.sum(l_flow[self.OIL_COL]) > 0:
                    if np.sum(l_flow[self.GAS_COL])/np.sum(l_flow[self.OIL_COL])> 3.2:
                        be_major = 'GAS'
                        break_even =(np.sum(dc_rev)- np.sum(l_flow['dcf']))/np.sum(l_flow[self.GAS_COL])
                    else:    
                        be_major = 'OIL'
                        break_even =(np.sum(dc_rev)- np.sum(l_flow['dcf']))/np.sum(l_flow[self.OIL_COL])
                else:
                    be_major = 'GAS'
                    break_even =(np.sum(dc_rev)- np.sum(l_flow['dcf']))/np.sum(l_flow[self.GAS_COL])
            else:
                if self._breakeven_phase == "GAS":
                    be_major = 'GAS'
                    break_even =(np.sum(dc_rev)- np.sum(l_flow['dcf']))/np.sum(l_flow[self.GAS_COL])
                else:
                    be_major = 'OIL'
                    break_even =(np.sum(dc_rev)- np.sum(l_flow['dcf']))/np.sum(l_flow[self.OIL_COL])

            l_flow['cum_cf'] = l_flow['cf'].cumsum()
            positive_index = (l_flow['cum_cf'] > 0).idxmax()


            ind_dict['UWI'].append(w)
            ind_dict['EURO'].append(np.sum(l_flow[self.OIL_COL]))
            ind_dict['EURG'].append(np.sum(l_flow[self.GAS_COL]))
            ind_dict['EURW'].append(np.sum(l_flow[self.WATER_COL]))
            ind_dict['REVENUE'].append(np.sum(l_flow['revenue']))
            ind_dict['ROYALTY'].append(np.sum(l_flow['royalty']))
            ind_dict['OPEX'].append(np.sum(l_flow['expense']))
            ind_dict['TAXES'].append(np.sum(l_flow['taxes']))
            ind_dict['CAPEX'].append(np.sum(l_flow['capex']))
            ind_dict['FCF'].append(np.sum(l_flow['cf']))
            ind_dict['DCF'].append(np.sum(l_flow['dcf']))
            ind_dict['BREAKEVEN'].append(break_even)
            ind_dict['BREAKEVEN_PHASE'].append(be_major)
            ind_dict['PAYOUT'].append(positive_index)

            #if np.sum(cf_array) > 0:
            try:
                l_npv = npv_calc(l_flow['cf'].to_numpy())
                #print(l_npv.get_npv(0))
                ind_dict['IRR'].append(l_npv.get_irr())
            except:
                ind_dict['IRR'].append(0)

            ind_dict['ROI'].append(np.sum(l_flow['cf'])/np.sum(l_flow['capex'])+1)
            #else:
            #    ind_dict['IRR'].append(0)


        self._indicators = pd.DataFrame(ind_dict)

    def generate_cashflow(self):
        r_df = pd.DataFrame([])
        unique_wells = self._flowstreams[self._flowstream_uwi_col].unique()

        iterable = tqdm(unique_wells) if self._verbose else unique_wells

        for w in iterable:
            l_flow = self.well_flowstream(w)

            if r_df.empty:
                r_df = l_flow
            else:
                r_df = pd.concat([r_df,l_flow])

        return r_df