// Beat bloom: expanding rings on each beat; spectrum shapes the ring; bass glows the core.
// nv:scale=0.33
float spec(float x){ return texture(iChannel0, vec2(clamp(x,0.0,1.0),0.25)).r; }

void mainImage(out vec4 c, in vec2 p){
  vec2 q = (p - 0.5*iResolution.xy) / iResolution.y;
  float r = length(q), a = atan(q.y,q.x);
  float beat = iBeat.x * iBeat.w, ph = iBeat.y, bass = iLevel.x, treb = iLevel.z;
  vec3 col = vec3(0.008,0.010,0.025);
  col += vec3(0.05,0.03,0.10) * (1.0 - r*0.8);
  for (int k=0;k<3;k++){
    float fk=float(k);
    float ring = fract(ph + fk*0.333);
    float rad = 0.10 + 0.55*ring;
    float band = spec(fract(fk*0.21 + 0.05));
    float w = 0.006 + 0.02*band + 0.01*beat;
    float glow = exp(-abs(r-rad)/w) * (0.35 + 0.8*beat) * (1.0 - ring*0.6);
    vec3 hue = 0.5 + 0.5*cos(6.2831*(fk*0.18 + iTime*0.04 + vec3(0.0,0.33,0.67)));
    col += hue * glow * (0.6 + 0.9*band);
  }
  col += vec3(1.0,0.55,0.25) * exp(-r*(12.0 - 5.0*bass)) * (0.15 + 1.2*beat);
  col += vec3(0.4,0.7,1.0) * exp(-r*5.0) * bass * 0.25;
  float sp = fract(sin(dot(floor(p/2.0), vec2(12.9898,78.233)) + floor(iTime*10.0))*43758.5);
  col += step(0.998 - 0.0015*treb, sp) * smoothstep(0.7,0.2,r) * treb * 0.6;
  col *= 1.0 + 0.10*beat*beat;
  c = vec4(1.0-exp(-col*1.6), 1.0);
}
