import rawpy
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import tifffile
import sys

np.seterr(divide='ignore', invalid='ignore') #suppress nans and infs warnings

rawextension = sys.argv[1] #search for these RAW extensions
gamma = float(sys.argv[2]) #set output gamma

icc_profile_path = "ProPhotoLinear.icm" #use attached linear profile
icc_file = open(icc_profile_path, "rb")
icc_profile = icc_file.read()

importparams = rawpy.Params(output_color=rawpy.ColorSpace.raw,
                            output_bps=16,
                            gamma=(1,1),
                            no_auto_scale=True,
                            no_auto_bright=True,
                            half_size=False,
                            user_wb=[1.0, 1.0, 1.0, 1.0])

Path("Inverted").mkdir(parents=True, exist_ok=True)

#look through all RAW files alphabetically, 0th and 1st are flat and bw frames
raw_files = sorted(Path.cwd().glob("*."+rawextension)) 
flatfield_path = str(raw_files[0])
blackwhite_path = str(raw_files[1])

#read bw and flat frames
print('Processing flat-field')
flat = rawpy.imread(flatfield_path)
flat = flat.postprocess(importparams)

print('Processing half-exposed leader')
bw = rawpy.imread(blackwhite_path)
bw = bw.postprocess(importparams)

#define mask for black and white points
dimensions = np.shape(bw)
exposed_xmin = round(dimensions[1]/6)
exposed_xmax = round(2*dimensions[1]/6)
base_xmin = round(4*dimensions[1]/6)
base_xmax = round(5*dimensions[1]/6)
ymin = round(dimensions[0]/3)
ymax = round(2*dimensions[0]/3)

#calculate density of base and exposed leader
exposedintensity = np.mean(bw[ymin:ymax,exposed_xmin:exposed_xmax,:],axis=(0,1))
baseintensity = np.mean(bw[ymin:ymax,base_xmin:base_xmax,:],axis=(0,1))
exposedi0 = np.mean(flat[ymin:ymax,exposed_xmin:exposed_xmax,:],axis=(0,1))
basei0 = np.mean(flat[ymin:ymax,base_xmin:base_xmax,:],axis=(0,1))
print('Base density = ' , end="")
basedensity = np.log10(basei0/baseintensity)
print(basedensity)
print('Exposed density = ' , end="")
exposeddensity = np.log10(exposedi0/exposedintensity)
print(exposeddensity)


#process scans
for file in raw_files[2:]:
    print('Inverting ' + file.name)
    scan = rawpy.imread(str(file))
    scan = scan.postprocess(importparams)
    
    scan = np.log10(flat/scan)#calculate density
    scan = (scan-basedensity)/(exposeddensity-basedensity)#scale density to 0-1

    scan = (np.power(10,scan*gamma)-1)/(np.power(10,gamma)-1) #base curve
    
    scan[np.isnan(scan)]=0 #clean for export
    scan = np.clip(scan,0,1)
    
    tifffile.imwrite(
                "Inverted"+str(Path("/"))+file.stem+".tiff",
                (scan * 65535).astype(np.uint16),
                photometric='rgb',
                extratags=[(34675, 'B', len(icc_profile), icc_profile, True)]
            )
