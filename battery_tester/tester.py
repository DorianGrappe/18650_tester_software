import pandas as pd
import time
from datetime import datetime
import sys
import os.path


try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM) # GPIO Numbers instead of board numbers
    import busio
    import digitalio
    import board
    import adafruit_mcp3xxx.mcp3008 as MCP
    from adafruit_mcp3xxx.analog_in import AnalogIn
except:
    # we are not on a raspberry, but we still can do some tests
    from battery_tester.rpi_mock import *


# ==== global parameters ====
# voltage under which we consider the battery as discharged
discharged_voltage = 3
# voltage above which we consider the battery as new
min_charged_voltage = 4
# value of the resistor
R = 3 # Ohm
# maximum voltage that we can read when there is no battery in the slot
voltage_empty_slot = 1
# voltage under which the cell won't be charged 
too_low_voltage = 2.9
# nb of slot test
nb_slot = 5

# has the cell already been charged
already_tested = [False]*nb_slot
# has the cell already been tested
charged_once = [False]*nb_slot
# cell ready to be unpluged
charged_twice = [False]*nb_slot

def close_relay(slot_id, slot_infos):
    # ==== close the relay ====
    RELAY_GPIO = slot_infos[slot_id]["relay_gpio"]
    # GPIO Assign mode
    GPIO.setup(RELAY_GPIO, GPIO.OUT)
    # close the relay
    GPIO.output(RELAY_GPIO, GPIO.LOW)
    slot_infos[slot_id]["relay_open"] = False
    time.sleep(0.5)
    return


def open_relay(slot_id, slot_infos):
    # ==== close the relay ====
    RELAY_GPIO = slot_infos[slot_id]["relay_gpio"]
    # GPIO Assign mode
    GPIO.setup(RELAY_GPIO, GPIO.OUT)
    # close the relay
    GPIO.output(RELAY_GPIO, GPIO.HIGH)
    slot_infos[slot_id]["relay_open"] = True
    time.sleep(0.5)
    return


def read_voltage(slot_id, slot_infos, mcp):
    # create a differential ADC channel between Pin 0 and Pin 1
    pin0 = slot_infos[slot_id]["mcp_pin0"]
    pin1 = slot_infos[slot_id]["mcp_pin1"]
    time.sleep(0.1)
    voltage = AnalogIn(mcp, pin0, pin1).voltage / 3.3 * 5
    return voltage


def read_all_voltages_t(slot_infos, mcp):
    for slot_id in list(slot_infos.keys()):
        close_relay(slot_id, slot_infos)
        time.sleep(0.1)
        voltage = read_voltage(slot_id, slot_infos, mcp)
        open_relay(slot_id, slot_infos)
        print('Voltage batt ' + str(slot_id) + ": " + str(voltage) + 'V')

def charging(slot_id):
    open_relay(slot_id, slot_infos)


def create_slot_info():
    slot_infos = {
        1: {"relay_gpio":5, "mcp_pin0": MCP.P0, "mcp_pin1": MCP.P1, "relay_open": True, "testing": False},
        2: {"relay_gpio":6, "mcp_pin0": MCP.P2, "mcp_pin1": MCP.P3, "relay_open": True, "testing": False},
        3: {"relay_gpio":13, "mcp_pin0": MCP.P4, "mcp_pin1": MCP.P5, "relay_open": True, "testing": False},
        4: {"relay_gpio":19, "mcp_pin0": MCP.P6, "mcp_pin1": MCP.P7, "relay_open": True, "testing": False}
    }
    return slot_infos

def relays_initialization(slot_infos, mcp, csv_file):
    mah = 0
    # close all the relays of the slots containing a charged battery
    df_slots_history = pd.DataFrame()
    for slot_id in list(slot_infos.keys()):
        open_relay(slot_id, slot_infos)
        voltage = read_voltage(slot_id, slot_infos, mcp)

        # we record it
        if os.path.isfile(csv_file):
            df = pd.read_csv(csv_file)
            if df[df.slot_id == slot_id].shape[0] > 0:
                testing_session = int(df[df.slot_id == slot_id].testing_session.values[-1])
            else:
                testing_session = 0
        else:
            testing_session = 0
        slot_measure = pd.Series(
            data=[datetime.now(), slot_id, voltage, False, testing_session, mah],
            index=['time', 'slot_id', 'voltage', 'testing', 'testing_session', 'spent_mah']
        )
        df_slots_history = df_slots_history.append(slot_measure, ignore_index=True)

        # if the battery is charged, we test it
        if voltage > min_charged_voltage:
            close_relay(slot_id, slot_infos)

            # we record it (we read the voltage again, in case the relay is closed)
            voltage = read_voltage(slot_id, slot_infos, mcp)
            
            slot_measure = pd.Series(
                data=[datetime.now(), slot_id, voltage, True, testing_session, mah],
                index=['time', 'slot_id', 'voltage', 'testing', 'testing_session', 'spent_mah']
            )

            df = pd.DataFrame(slot_measure)
            df[0] = df[0].astype(str)
            if os.path.isfile(csv_file):
                df.T.to_csv(csv_file, mode='a', header=False, index=False)
            else:
                df.T.to_csv(csv_file, index=False)

            df_slots_history = df_slots_history.append(slot_measure, ignore_index=True)
    return df_slots_history


def main_function(csv_file='output/measures.csv'):
    slot_infos = {
        1: {"relay_gpio":5, "mcp_pin0": MCP.P0, "mcp_pin1": MCP.P1, "relay_open": True, "testing": False},
        2: {"relay_gpio":6, "mcp_pin0": MCP.P2, "mcp_pin1": MCP.P3, "relay_open": True, "testing": False},
        3: {"relay_gpio":13, "mcp_pin0": MCP.P4, "mcp_pin1": MCP.P5, "relay_open": True, "testing": False},
        4: {"relay_gpio":19, "mcp_pin0": MCP.P6, "mcp_pin1": MCP.P7, "relay_open": True, "testing": False}
    }

    # ==== MCP3008 hardware SPI configuration ====
    spi = busio.SPI(clock=board.SCK, MISO=board.MISO, MOSI=board.MOSI)
    # create the cs (chip select)
    cs = digitalio.DigitalInOut(board.CE0)
    # create the mcp object (harware option)
    mcp = MCP.MCP3008(spi, cs)
    # is the charge finished
    stagne = [False]*nb_slot    

    # ==== beginning of the capacity measure ====
    # we initialize the relays only at the beginning
    if not os.path.exists(csv_file):
        df_slots_history = relays_initialization(slot_infos, mcp, csv_file)
        first_measure = True
    else:
        df_slots_history = pd.read_csv(csv_file)
        first_measure = False
        
    # print('===========')
    for slot_id in list(slot_infos.keys()):
        
        # we read the voltage of the battery
        voltage = read_voltage(slot_id, slot_infos, mcp)
        last_measure = df_slots_history[df_slots_history.slot_id == slot_id].tail(1)
        last_testing_session = last_measure.testing_session.values[0]
        last_testing = bool(last_measure.testing.values[0])
        last_voltage = float(last_measure.voltage.values[0])
        last_mah = float(last_measure.spent_mah.values[0])
        mah = 0

        if (size(df_slots_history[df_slots_history.slot_id == slot_id]) >= 12 ):
            # Recuperation des points n-10;n-9;n-8 et n-2;n-1;n
            last_values = df_slots_history[df_slots_history.slot_id == slot_id].tail(12)
            n_12 = last_values[11]
            n_11 = last_values[10]
            n_10 = last_values[9]
            n_2 = last_values[1]
            n_1 = last_values[0]

            # we check if the cell is still charging or not
            variation = abs((n_12+2*n_11+n_10)/4 -(n_2+2*n_1+voltage)/4)

            if (variation < 0.3):
                stagne[slot_id] = True

        

        # =============  ==================
        # From empty to plugged

        former_cell_value = df_slots_history[
                (df_slots_history.slot_id == slot_id)
                & (df_slots_history.testing_session == last_testing_session)
                & (df_slots_history.testing == True)].tail(1)
        
        if (
            (voltage > voltage_empty_slot)
            and (last_voltage <= voltage_empty_slot)):
        
        #  is it a new one ?
            if not (( voltage >= (former_cell_value - 0.1) )
                and ( voltage <= (former_cell_value + 0.1) )):
                last_testing_session = float(last_testing_session) + 1
                last_testing = False



        # ============= Case 0 ==================
        # Cell needs to be charged

        # - wasn't charged yet 
        # - and current voltage > too_low_voltage
        # - no fully charged
        #  the relay remains open
    
        if (
            (voltage > too_low_voltage)
            and (charged_once[slot_id] == False)
            and (stagne[slot_id] == False)):

            open_relay(slot_id)
            last_testing = False
            print("Case 0, Charging")
            print(' cell has' + str(voltage) + 'V') 
         

        # ============= Case 1 ==================
        # Cell voltage too low to be charged

        # - voltage too low to be charged
        # - and current voltage < too_low_voltage
        # print("cell too low to be charged", voltage)

        elif (
            (voltage < too_low_voltage)
            and (voltage > voltage_empty_slot)):
            
            last_testing = False
            open_relay(slot_id)
            print("Case 1, The cell voltage is too low to be charged")
            print(' Cell has ' + str(voltage) + 'V')

        # ============= Case 2 ==================
        # Empty slot 

        # - voltage < voltage_empty_slot
        # print("insert a cell")

        elif (
            (voltage < voltage_empty_slot) 
            and (charged_twice[slot_id] == False)
            ):

            print("Case 2, Insert a cell")
            if last_testing:
                print("test interrupted")
                last_testing = False
                open_relay(slot_id, slot_infos)

        # ============= Case 3 ==================
        #  the cell is charged

        # - charged_once = false
        # - v > too_low_voltage
        # we OPEN A NEW COLUMN and close the relay to discharge
        # print("End of charge", last_voltage, voltage, last_testing)

        elif (
            (charged_once[slot_id] == False)
            and (voltage > too_low_voltage)
            and (stagne[slot_id] == True)
        ):
            close_relay(slot_id, slot_infos)
            charged_once[slot_id] = True
            last_testing = False
            stagne[slot_id] = False
            print("Case 3, End of charge")


        # ============= Case 4 ==================
        # - already charged
        # - cell not discharged yet
        # - slot not empty
        # relay remains closed and data registered
        # print("Discharging", last_voltage, voltage, last_testing)

        elif (
            (charged_once[slot_id] == True)
            and (voltage >= discharged_voltage)
            and (already_tested[slot_id] == False)
        ):

            close_relay(slot_id, slot_infos)
            print("Discharging", last_voltage, voltage, last_testing)


        # ============= Case 5 ==================
        # - end of test
 
        # - charged once
        # - voltage under discharged voltage
        # the dischargement is finished
        # we send the conclusions and open the relay
        # print("-----", last_voltage, voltage, last_testing)

        elif (
            (charged_once[slot_id] == True)
            and (voltage <= discharged_voltage)
            and (voltage > voltage_empty_slot)
            and (already_tested[slot_id] == False)
        ):
            print("Case 5, end of battery testing")
            
            # we calculate the total capacity
            df_testing_session = df_slots_history[
                (df_slots_history.slot_id == slot_id)
                & (df_slots_history.testing_session == last_testing_session)
                & (df_slots_history.testing == True)
            ]
            battery_capacity = df_testing_session.spent_mah.max()
            print('battery ' + str(slot_id) + ' tested at ' + str(round(battery_capacity, 0)) + ' mAh')
            
            # export to file
            filename = str(datetime.now())[0:19].replace(":", "") + "_" + str(slot_id) + "_" + str(int(last_testing_session)) + "_" + str(int(battery_capacity)) + "mAh.csv"
            df_testing_session.to_csv("output/" + filename, sep=",", index=False)
            
            open_relay(slot_id, slot_infos)
            last_testing = False
            already_tested[slot_id] = True

        # ============= Case 6 ============= 
        # - cell already tested
        # - not charged for the 2nd time yet
        # this means that the battery is not recharged yet
        # start recharging 
        # - the battery was already tested: reset
        
        elif (
            (already_tested[slot_id] == True)
            and (stagne[slot_id] == False)
        ):
            print("Case 6, Under charge")
            last_testing = False
  

        # ============= Case 7 =============
        #  Battery ready to take off

        # - already tested
        # - fully recharged
        # this means that the battery is fully recharged
       
        elif (
            (already_tested[slot_id] == True)
            and (stagne[slot_id] == True)
            
        ):
            
            print("Case 7, the battery is fully charged, Test finished")

            charged_twice[slot_id] = True
            
         # ============= Case 8 =============
         # end of session, battery retrieved

        # - already tested
        # - fully recharged
        # - empty slot
       
        elif (
            (voltage <= voltage_empty_slot)
            and (charged_twice[slot_id] == True)
            
        ):
            
            print("Case 8, insert new battery")

            charged_twice[slot_id] = False
            already_tested[slot_id] = False
            charged_once[slot_id] = False
                


              
     
        timenow = datetime.now()
        if last_testing == True:
            delta_t = (timenow - pd.to_datetime(df_slots_history[df_slots_history.slot_id == slot_id].iloc[-1].time)) / pd.Timedelta(1, "s")
            mah = round(last_mah + voltage / R / 3600 * 1000 * delta_t, 3)
        voltage = round(voltage, 3)
        
        slot_measure = pd.Series(
                data=[timenow, slot_id, voltage, last_testing, last_testing_session, mah],
                index=['time', 'slot_id', 'voltage', 'testing', 'testing_session', 'spent_mah']
            )
        df_slots_history = df_slots_history.append(slot_measure, ignore_index=True)
        
        df = pd.DataFrame(slot_measure)
        df[0] = df[0].astype(str)

        # if not ( (voltage < voltage_empty_slot) and (last_voltage < voltage_empty_slot) ):
        if True:
            if os.path.isfile(csv_file):
                df.T.to_csv(csv_file, mode='a', header=False, index=False)
            else:
                if not os.path.exists("output"):
                    os.mkdir("output")
                df.T.to_csv(csv_file, index=False)

        if last_testing == True:
            print('batt ' + str(slot_id) + ": " + str(last_voltage) + "/" + str(voltage))
    
    if first_measure:
        # we remove the data created by the initialization function
        # we did not remove it before, because we need it to calculate if a test is starting
        df_slots_history = df_slots_history.iloc[4:]

    return df_slots_history

