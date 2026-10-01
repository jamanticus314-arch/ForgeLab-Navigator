Q=1<<18; MASK64=(1<<64)-1
def truncdiv(a,b):
 return (abs(a)//abs(b))*(-1 if (a<0) != (b<0) else 1)

def power_q18(q8):
 """Exact inlined Q18 mass^(5/8), support tested q8=40..450."""
 x=q8<<10
 if x==Q:return Q
 if not x:return 0
 k=0
 while x<Q:
  x=(x*0xadf85459)>>30;k-=1
 while x>=0xadf86:
  x=(x<<30)//0xadf85459;k+=1
 t=((x-Q)<<18)//(x+Q)
 square=(t*t)>>18
 term=t;total=0;denominator=Q
 while True:
  value=(term<<18)//denominator
  term=(term*square)>>18
  total+=value;denominator+=2*Q
  if value<=1:break
 half_ln=(k<<17)+total
 exponent=(half_ln*5)>>2
 if exponent==0:return Q
 negative=exponent<0
 magnitude=abs(exponent)
 nq=truncdiv(magnitude<<18,0x2c5c8)&-Q
 n=nq>>18
 if n>=64:result=(1<<63)-1
 else:
  remainder=magnitude-((nq*0x2c5c8)>>18)
  term=Q;result=Q;denominator=Q
  while True:
   ratio=truncdiv(remainder<<18,denominator)
   denominator+=Q
   term=(term*ratio)>>18
   result+=term
   if abs(term)<=1:break
  result=result<<n
  if result>=(1<<63):result=(1<<63)-1
 return truncdiv(1<<36,result) if negative else result

def minstd(state):
 # Exact Schrage branch for uint32 states as native code receives them.
 hi=state//44488;lo=state-hi*44488
 a=(lo*48271)&0xffffffff;b=(hi*3399)&0xffffffff
 d=(a-b)&0xffffffff
 return d if b<a else (d+0x7fffffff)&0xffffffff

def factor_from_word3e(signed_word):
 # Literal signed-high multiply and shifts from 0x3c373f9..0x3c3745d.
 numerator=signed_word<<40
 high=(numerator*0x6d3a06d3a06d3a07)>>64
 quotient=high>>29
 quotient+=(quotient & MASK64)>>63
 factor=quotient+(1<<24)
 if factor<0:factor=1<<24
 return factor>>6

def forward(q8,state,signed_word=0):
 power=power_q18(q8)
 tstate=minstd(state);tjitter=tstate%52429+235929
 temperature=((((tjitter*0x5a480000)>>18)*power)>>18)
 temperature=(temperature*factor_from_word3e(signed_word))>>36
 rstate=minstd(tstate);rjitter=rstate%52429+235929
 radius=(rjitter*power)>>21
 return {'q8':q8,'state_before':state,'signed_word_3e':signed_word,'power_q18':power,'state_temperature':tstate,'jitter_temperature_q18':tjitter,'temperature':temperature&0xffffffff,'state_radius':rstate,'jitter_radius_q18':rjitter,'qR15':radius&0xffffffff}

