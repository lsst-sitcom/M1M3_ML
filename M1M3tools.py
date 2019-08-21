import os
import sys
import h5py
import numpy as np
from scipy import interpolate
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from datetime import timedelta

from os.path import expanduser

import MySQLdb as mdb
from sqlalchemy import create_engine
#from sqlalchemy import exc

from FATABLE import *


m3ORC = 2.508
m3IRC = 0.550
m1ORC = 4.18
m1IRC = 2.558

home = os.path.expanduser("~")
dataDir  = os.path.join(home, 'largeData', 'M1M3_ML')
BMPatchDir = os.path.join(dataDir, 'LSST_BM_patch_190508')

fat = np.array(FATABLE)
actID = np.int16(fat[:, FATABLE_ID])
nActuator = actID.shape[0]
xact = np.float64(fat[:, FATABLE_XPOSITION])
yact = np.float64(fat[:, FATABLE_YPOSITION])

def readH5Map(fileset, dataset = '/dataset'):
    '''
    The method takes a list of h5 files, get the images, and average them to get a combined image array.
    input:
    fileset is a list of filenames, which can be relative path for the dataset, or absolute path.
    dataset refers to where the image array is stored in the h5 file
    output:
    data, which is the averaged image array
    centerRow, centerCol, pixelSize
    '''
    i = 0
    if len(fileset) == 0:
        print('Error: empty fileset')
        sys.exit()
    for filename in fileset:
        #print(filename)
        h5file = os.path.join(dataDir, filename)
        f = h5py.File(h5file,'r')
        data0 = f[dataset]
        if 'date' in data0.attrs.keys():
            if len(data0.attrs['date']) == 1:
                timeStamp = data0.attrs['date'][0].decode('ascii')
            else:
                timeStamp = data0.attrs['date'].decode('ascii')
        else:
            timeStamp = 'date not in h5 file.'
        if i==0:
            centerRow = data0.attrs['centerRow']
            centerCol = data0.attrs['centerCol']
            pixelSize = data0.attrs['pixelSize']
            data = data0[:]
        else:
            data += data0[:]
        f.close()
        if filename.find(dataDir) == 0:
            filenameShort = filename[len(dataDir):]
        else:
            filenameShort = filename
        #print('%s: %s is %d x %d, pixelSize = %.4f'%(
        #    filenameShort, dataset, data.shape[0], data.shape[1], pixelSize))

        print('%s: %s '%(filenameShort, timeStamp))
        i+=1
    data /= i
    data = np.rot90(data, 1) # so that we can use imshow(data, origin='lower')
    return data, centerRow, centerCol, pixelSize

def getH5date():
    return 1
    
def mkXYGrid(s, centerRow, centerCol, pixelSize):
    '''
    construct the x and y mesh grid corresponding to the image array in the h5 files.
    '''
    [row, col] = s.shape
    xVec = np.arange(1, col+1)
    xVec = (xVec - centerCol) * pixelSize
    yVec = np.arange(1, row+1)
    yVec = (yVec - centerRow) * pixelSize #if we don't put negative sign, we have to flipud the image array
    [x, y] = np.meshgrid(xVec, yVec)
    return x,y

def mkM1M3disp(m1s, m3s, x1, y1, x3, y3):
    '''
    takes the m1 and m3 surfaces, interpolate m3 onto m1 grid, so that we can display then as one plot.
    '''
    s = m1s
    r1 = np.sqrt(x1**2 + y1**2)
    idx = (r1<m3ORC)*(r1>m3IRC)
    m3s[np.isnan(m3s)] = 0
    f = interpolate.interp2d(x3[0,:], y3[:,0], m3s)
    s_temp = f(x1[0,:], y1[:,0])
    s[idx] = s_temp[idx]
    return s


def create_connection1():
    default_file = os.path.join(os.path.expanduser('~/'), 'Documents', 'efd.cnf')
    return mdb.connect(host="140.252.32.246", user="efduser", passwd="lssttest", db="EFD")
def create_connection2():
    default_file = os.path.join(os.path.expanduser('~/'), 'Documents', 'efd.cnf')
    return mdb.connect(host="140.252.32.142", user="efduser", passwd="lssttest", db="EFD")

engine1 = create_engine('mysql+mysqldb://', creator=create_connection1)
engine2 = create_engine('mysql+mysqldb://', creator=create_connection2)

def get_dataframe_EFD(myt, table_name = 'm1m3_logevent_AppliedForces'):
    [month, day, hour, minute] = myt
    b0 = datetime(2019, month, day, hour, minute, 0)
    b1 = b0 + timedelta(minutes = -2)
    b2 = b0 + timedelta(minutes = 2)
    query = 'select * from {0} where {0}.date_time between \'{1}\' and \'{2}\';'.format(table_name, b1, b2)
    namestr = table_name.split('_')[-1]
    filename = 'efdData/%s_%s.csv'%(namestr, (b1+(b2-b1)/2).strftime("%y%m%d_%H%M"))
    if not os.path.isfile(filename):
        print(query)
        if month ==1:
            df1 = pd.read_sql_query(query, engine1)
        else:
            df1 = pd.read_sql_query(query, engine2)
        df1.to_csv(filename)
    else:
        print('-------Reading from %s-------------'%filename)
        df1 = pd.read_csv(filename,parse_dates=['date_time']) #make sure dtype for date_time column is understood
    return df1

def get_F_EFD(myt, table_name = 'm1m3_logevent_AppliedForces'):
    df1 = get_dataframe_EFD(myt, table_name)
    F = assembleFfromEFD(df1, campn = myt[0])
    return F

def get_F_EFD_C1C2(myt, table_name='m1m3_logevent_AppliedCylinderForces'):
    df1 = get_dataframe_EFD(myt, table_name)
    F = assembleFfromEFD_C1C2(df1, campn = myt[0])
    return F

def assembleFfromEFD(df1, campn = 1, output=0):
    '''
    df1 is a pandas frame, which is result of a query to table m1m3_logevent_AppliedForces
    This assumes x/y/z forces from invidual actuators are stored as separate columns

    output:
    col 0: actuator IDs
    col 1: x force
    col 2: y force
    col 3: z force
    '''
    myF = np.zeros((nActuator, 4)) #ID, x, y, z
    myF[:, 0] = actID
    xexist = 1
    yexist = 1
    zexist = 1
    for i in range(nActuator):
        ix = FATABLE[i][FATABLE_XINDEX]
        iy = FATABLE[i][FATABLE_YINDEX]
        if campn == 1:
            try:
                myF[i, 3] = np.mean(df1['ZForces_%d'%(i+1)]) #Fz
            except KeyError:
                myF[i, 3] = np.mean(df1['ZForce_%d'%(i+1)]) #Fz
        elif campn == 2:
            if len(df1.ZForces)>0 and len(df1.ZForces[0].split())==156:
                myF[i, 3] = np.mean([float(df1.ZForces[ii].split()[i]) 
                       for ii in range(len(df1.ZForces))])
            else:
                zexist = 0
        if ix != -1:
            # x forces in campn 2 were NOT changed into strings. Only y and z forces
            try:
                myF[i, 1] = np.mean(df1['XForces_%d'%(ix+1)]) #Fx, note ix starts with 0
            except KeyError:
                try:
                    myF[i, 1] = np.mean(df1['XForce_%d'%(ix+1)]) #Fx, note ix starts with 0
                except KeyError:
                    xexist = 0
        if iy != -1:
            if campn == 1:
                try:
                    myF[i, 2] = np.mean(df1['YForces_%d'%(iy+1)]) #Fx, note ix starts with 0
                except KeyError:
                    try:
                        myF[i, 2] = np.mean(df1['YForce_%d'%(iy+1)]) #Fx, note ix starts with 0
                    except KeyError:
                        yexist = 0
            elif campn == 2:
                try:
                    myF[i, 2] = np.mean([float(df1.YForces[ii].split()[iy]) 
                       for ii in range(len(df1.YForces))])
                except AttributeError:
                    zexist = 0
        if output:
            print('%d, %6.1f %6.1f %8.1f'%(myF[i, 0],myF[i, 1],myF[i, 2],myF[i, 3]))

    if not xexist:
        print('---No XForces---')
    if not yexist:
        print('---No YForces---')
    if not zexist:
        print('---No ZForces---')        
    return myF

def assembleFfromEFD_C1C2(df1, campn =1, output=0):
    '''
    df1 is a pandas frame, which is result of a query to table m1m3_logevent_AppliedCylinderForces
    This assumes x/y/z forces from invidual actuators are stored as separate columns

    output:
    col 0: actuator IDs
    col 1: x force
    col 2: y force
    col 3: z force
    '''
    myF = np.zeros((nActuator, 4)) #ID, x, y, z
    myF[:, 0] = actID
    for i in range(nActuator):
        idaa = FATABLE[i][FATABLE_SINDEX]
        orientation = FATABLE[i][FATABLE_ORIENTATION]
        if campn == 1:
            fc1 = np.mean(df1['PrimaryCylinderForces_%d'%(i+1)])/1000.
        else:
            fc1 = np.mean([float(df1.PrimaryCylinderForces[ii].split()[i]) 
                       for ii in range(len(df1.PrimaryCylinderForces))])/1000
        myF[i, 3] = fc1
        if orientation == 'NA':
            pass
        else:
            if campn == 1:
                fc2 = np.mean(df1['SecondaryCylinderForces_%d'%(idaa+1)])/1000.
            else:
                fc2 = np.mean([float(df1.SecondaryCylinderForces[ii].split()[idaa]) 
                       for ii in range(len(df1.SecondaryCylinderForces))])/1000
            myF[i, 3] += fc2*0.707 #Fz
            if orientation == '+X':
                myF[i, 1] = fc2*0.707
            elif orientation == '-X':
                myF[i, 1] = -fc2*0.707
            elif orientation == '+Y':
                myF[i, 2] = fc2*0.707
            elif orientation == '-Y':
                myF[i, 2] = -fc2*0.707
            else:
                print('--- UNKNOWN CYLINDER 2 ORIENTATION ---')
        if output:
            print('%d, %6.1f %6.1f %8.1f'%(myF[i, 0],myF[i, 1],myF[i, 2],myF[i, 3]))
    return myF




dft = pd.read_csv('%s/Telescope_Cell_Data/Temperatures/lsst_tc_190114.txt'%(dataDir), comment='%',nrows=87)

def getEFDTMatrix(df1):
    '''
    returns matrix 87 x 4
col 1 = idx (1=F, 2=B, 3=M, 4=amb)
col 2 = x
col 3 = y
col 4 = T
    '''
    ntc = len(dft)
    m = np.zeros((ntc,4))
    for i in range(ntc):
        inst = dft[' which_ag'][i]+1 #index starts with 1 in EFD
        chan = dft[' index'][i]+1
        if dft[' name'][i].strip().startswith('F'):
            m[i, 0] = 1
        elif dft[' name'][i].strip().startswith('B'):
            m[i, 0] = 2
        elif dft[' name'][i].strip().startswith('M'):
            m[i, 0] = 3
        elif dft[' name'][i].strip().startswith('amb'):
            m[i, 0] = 4
        m[i, 1] = dft[' x(in)'][i]
        m[i, 2] = dft[' y(in)'][i]
        m[i, 3] = df1['thermocoupleScanner%d_%d'%(inst, chan)]
    print('Number of Face Plate TCs = %d'%sum(m[:,0]==1))
    print('Number of Back Plate TCs = %d'%sum(m[:,0]==2))

    # add an extra column so that face plate TCs point to their corresponding back plate TCs
    m = m[np.argsort(m[:,0]),:]
    m1 = np.hstack([m, np.zeros((87,1))])
    idx = (m[:,0]==2)
    m[~idx, 1] = 1e8 #we destroy m, so that we can easily exclude TCs not on back plate when we do the search
    m[~idx, 2] = 1e8

    ntc=87
    for i in range(ntc):
        if m1[i,0]==1: #face plate
            d = np.sqrt( (m[:,1]-m1[i,1])**2 + (m[:,2]-m1[i,2])**2 )
            j = np.where(d<1e-2)[0][0]
            m1[i, -1] = j
            m1[j, -1] = i
    return m1

def plotEFDT(m):
    fig, ax = plt.subplots(2,2, figsize=(10, 8))
    #face plate
    idx1 = m[:,0]==1
    img = ax[0][0].scatter(m[idx1,1], m[idx1,2], 1e3*(m[idx1,3]-min(m[idx1,3])), (m[idx1,3]))
    ax[0][0].axis('equal')
    plt.colorbar(img, ax=ax[0][0])
    ax[0][0].set_title('Face plate')
    
    #back plate
    idx2 = m[:,0]==2
    img = ax[0][1].scatter(m[idx2,1], m[idx2,2], 1e3*(m[idx2,3]-min(m[idx2,3])), (m[idx2,3]))
    ax[0][1].axis('equal')
    plt.colorbar(img, ax=ax[0][1])
    ax[0][1].set_title('Back plate')
    
    #average
    x = m[idx1,1]
    y = m[idx1,2]
    t1 = m[idx1,3]
    t2 = m[m[idx1,4].astype(int),3]
    aver = (t1+t2)/2
    img = ax[1][0].scatter(x,y,1e3*(aver - min(aver)), aver)
    ax[1][0].axis('equal')
    plt.colorbar(img, ax=ax[1][0])
    ax[1][0].set_title('Average')
    
    #Diff
    diff = (t1-t2)
    img = ax[1][1].scatter(x,y,1e3*abs(diff), diff)
    ax[1][1].axis('equal')
    plt.colorbar(img, ax=ax[1][1])
    ax[1][1].set_title('Face - Back')


initialOptimizedForces = np.zeros(nActuator)
bendingForces = np.zeros(nActuator)
staticForces = np.zeros(nActuator)
balanceForces = np.zeros(nActuator)
appliedForces = np.zeros(nActuator)
