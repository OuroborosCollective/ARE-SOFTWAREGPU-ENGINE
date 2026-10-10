ClearAll[a,b,c,x,y,x0,x1,y0,y1,u,v,e];
e[x_,y_] := a x+b y+c;
weights={(1-u)(1-v),u(1-v),(1-u)v,u v};
corners={e[x0,y0],e[x1,y0],e[x0,y1],e[x1,y1]};
identity=TrueQ[Expand[e[x0+u(x1-x0),y0+v(y1-y0)]-weights.corners]===0];
sum=TrueQ[Expand[Total[weights]]===1];
tiles=Flatten[Table[{xx,yy},{yy,0,24,8},{xx,0,24,8}],1];
sampleE[xx_,yy_]:=20-(xx+1/2)-(yy+1/2);
classify[{xx_,yy_}]:=With[{values=Flatten[Table[sampleE[i,j],{i,{xx,xx+7}},{j,{yy,yy+7}}]]},Which[Min[values]>=0,"inside",Max[values]<0,"outside",True,"boundary"]];
types=classify/@tiles;
reference=Flatten[Table[sampleE[xx,yy]>=0,{yy,0,31},{xx,0,31}]];
optimized=Flatten[Table[With[{xx=t[[1]],yy=t[[2]],kind=classify[t]},Switch[kind,"inside",ConstantArray[True,64],"outside",ConstantArray[False,64],_,Flatten[Table[sampleE[i,j]>=0,{j,yy,yy+7},{i,xx,xx+7}]]]],{t,tiles}]];
referenceByTile=Flatten[Table[With[{xx=t[[1]],yy=t[[2]]},Flatten[Table[sampleE[i,j]>=0,{j,yy,yy+7},{i,xx,xx+7}]]],{t,tiles}]];
result=<|"protocol"->"are.wolfram-surface-oracle.v1","oracle"->"Wolfram Language exact rational computation","authority"->"none","affineCornerIdentity"->identity,"weightsSumToOne"->sum,"tileCounts"-><|"inside"->Count[types,"inside"],"boundary"->Count[types,"boundary"],"outside"->Count[types,"outside"]|>,"coveredPixels"->Count[reference,True],"sameCoverage"->(referenceByTile===optimized),"referenceEdgeEvaluations"->1024,"optimizedEdgeEvaluations"->(16*4+64*Count[types,"boundary"]),"ruleBoundary"->"real-affine-rectangular-domain; float32 implementation tested separately"|>;
ExportString[result,"RawJSON"]
