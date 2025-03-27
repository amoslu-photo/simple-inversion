import rawpy
import numpy as np
from pathlib import Path
import tifffile
import cv2
import argparse

np.seterr(divide='ignore', invalid='ignore') #suppress nans and infs warnings

#parse CLI inputs
parser = argparse.ArgumentParser(description="simple-inversion")

parser.add_argument('--rawext', type=str,default='CR3',help = 'RAW file extension, default CR3')
parser.add_argument('--gamma', type=float,default=1.0, help='Output base curve gamma')
parser.add_argument('--halfsize', action='store_true', help = 'Half-size RAW import for speed')
parser.add_argument('--processraw', action='store_true', help= 'Use RAW RGB rather than ProPhoto')
parser.add_argument('--processbw', action='store_true', help= 'Process black and white film')
parser.add_argument('--noautocrop', action='store_true', help='Disable automatic cropping to flat-field')
parser.add_argument('--mp',type=float,default=0.0,help='Megapixels to downscale to, default no scaling')

args = parser.parse_args()
rawextension = args.rawext
gamma = args.gamma
halfsizeimport = args.halfsize
processraw = args.processraw
processbw = args.processbw
noautocrop = args.noautocrop
megapixels = args.mp

#Load linear profiles for tiff tag
coloriccfile = open("ProPhotoLinear.icm" , "rb")
coloricc = coloriccfile.read()

grayiccfile = open("GrayLinear.icc" , "rb")
grayicc = grayiccfile.read()

#Hardcoded color conversion matrices
bradford_d65_to_d50 = np.array([[1.0478112,  0.0228866, -0.0501270],
                                [0.0295424,  0.9904844, -0.0170491],
                                [-0.0092345,  0.0150436,  0.7521316]])

xyztoprophoto = np.array([[ 1.3459433, -0.2556075, -0.0511118],
                      [-0.5445989,  1.5081673,  0.0205351],
                      [0.0000000,  0.0000000,  1.2118128]])


importparams = rawpy.Params(output_color=rawpy.ColorSpace.raw,
                            gamma=(1,1),
                            output_bps=16,
                            no_auto_scale=True,
                            no_auto_bright=True,
                            half_size=halfsizeimport
                            )

#-----------------------------------------------------------------------------
#Process roll

Path("Inverted").mkdir(parents=True, exist_ok=True)

#look through all RAW files alphabetically, 0th and 1st are flat and bw frames
raw_files = sorted(Path.cwd().glob("*."+rawextension)) 
flatfield_path = str(raw_files[0])
blackwhite_path = str(raw_files[1])

#read bw and flat frames
print('Processing flat-field')
raw = rawpy.imread(flatfield_path)
flat = raw.postprocess(importparams)

print('Processing half-exposed leader')
raw = rawpy.imread(blackwhite_path)
bw = raw.postprocess(importparams)

if not noautocrop: #finds bounding box from flatfield and crops
    cropmask = np.sum(flat,axis=(2))
    cropmask = cropmask>np.max(cropmask)/2 #selects one stop from max observed
    
    #finds box
    cropmaskx = np.any(cropmask,axis=(0))
    cropmasky = np.any(cropmask,axis=(1))
    cropmaskxmin = np.argmax(cropmaskx)
    cropmaskxmax = len(cropmaskx)-1-np.argmax(cropmaskx[::-1])
    cropmaskymin = np.argmax(cropmasky)
    cropmaskymax = len(cropmasky)-1-np.argmax(cropmasky[::-1])
    
    #crops flat and black
    flat = flat[cropmaskymin:cropmaskymax+1,cropmaskxmin:cropmaskxmax+1,]
    bw = bw[cropmaskymin:cropmaskymax+1,cropmaskxmin:cropmaskxmax+1,]

#calculate color conversion matrices
if not processbw: #color processing
    if not processraw: #prophoto colorspace
            xyztocamrgb = raw.rgb_xyz_matrix[0:3,0:3]
            conversionmatrix = xyztoprophoto  @ bradford_d65_to_d50 @  np.linalg.inv(xyztocamrgb)
    else:
            conversionmatrix = np.eye(3) #identity matrix
else:
    conversionmatrix = np.array([1.0,1.0,1.0]) #single channel

#convert raw to inversion colorspace
flat = flat @ conversionmatrix.T
bw = bw @ conversionmatrix.T

#define mask for black and white points
dimensions = np.shape(bw)
exposed_xmin = round(dimensions[1]/6)
exposed_xmax = round(2*dimensions[1]/6)
base_xmin = round(4*dimensions[1]/6)
base_xmax = round(5*dimensions[1]/6)
ymin = round(dimensions[0]/3)
ymax = round(2*dimensions[0]/3)

#if scaling enabled, calculate final image dimensions
if not megapixels == 0 : #do scaling
    scalefactor = np.sqrt(megapixels*1e6/dimensions[0]/dimensions[1])
    if scalefactor>=1:
        megapixels = 0 #do not enlarge image
    else:
        targetsize = (round(dimensions[1]*scalefactor),
                      round(dimensions[0]*scalefactor))

#calculate density of base and exposed leader
if bw.ndim == 3: #numpy complains about hanging dimension
    exposedintensity = np.mean(bw[ymin:ymax,exposed_xmin:exposed_xmax,:],axis=(0,1))
    baseintensity = np.mean(bw[ymin:ymax,base_xmin:base_xmax,:],axis=(0,1))
    exposedi0 = np.mean(flat[ymin:ymax,exposed_xmin:exposed_xmax,:],axis=(0,1))
    basei0 = np.mean(flat[ymin:ymax,base_xmin:base_xmax,:],axis=(0,1))
else:
    exposedintensity = np.mean(bw[ymin:ymax,exposed_xmin:exposed_xmax],axis=(0,1))
    baseintensity = np.mean(bw[ymin:ymax,base_xmin:base_xmax],axis=(0,1))
    exposedi0 = np.mean(flat[ymin:ymax,exposed_xmin:exposed_xmax],axis=(0,1))
    basei0 = np.mean(flat[ymin:ymax,base_xmin:base_xmax],axis=(0,1))

basedensity = np.log10(basei0/baseintensity)
exposeddensity = np.log10(exposedi0/exposedintensity)

print('Base density = ' , end="")
print(basedensity)
print('Exposed density = ' , end="")
print(exposeddensity)

#process scans
for file in raw_files[2:]:
    print('Inverting ' + file.name)
    raw = rawpy.imread(str(file))
    scan = raw.postprocess(importparams)
    if not noautocrop:
        
        scan = scan[cropmaskymin:cropmaskymax+1,cropmaskxmin:cropmaskxmax+1,]

    scan = scan @ conversionmatrix.T
    
    scan = np.log10(flat/scan)#calculate density
    scan = (scan-basedensity)/(exposeddensity-basedensity)#scale density to 0-1

    if not megapixels == 0 : #do scaling
        scan = cv2.resize(scan, targetsize, interpolation=cv2.INTER_AREA)

    
    scan = (np.power(10,scan*gamma)-1)/(np.power(10,gamma)-1) #base curve
    
    scan[np.isnan(scan)]=0 #clean for export
    scan = np.clip(scan,0,1)
    
    outputfilename = "Inverted"+str(Path("/"))+file.stem+".tiff"
    if processbw:
        tifffile.imwrite(
                outputfilename,
                (scan * 65535).astype(np.uint16),
                photometric="minisblack",
                extratags=[(34675, 'B', len(grayicc), grayicc, True)])
    else:
        tifffile.imwrite(
                outputfilename,
                (scan * 65535).astype(np.uint16),
                photometric="rgb",
                extratags=[(34675, 'B', len(coloricc), coloricc, True)])
        


        
    
