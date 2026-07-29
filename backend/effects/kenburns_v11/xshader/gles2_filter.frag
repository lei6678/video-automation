precision highp float;
varying vec2 uv0;
#define texCoord uv0

#define BLUR_MOTION 0x1
#define BLUR_SCALE  0x2

uniform float inputHeight;
uniform float inputWidth;

uniform float blurStep;
uniform mat4 u_InvModel;
uniform vec2 blurDirection;

uniform sampler2D _MainTex;
#define inputImageTexture _MainTex

#if defined(BLUR_TYPE) && BLUR_TYPE == BLUR_SCALE
#define num 25
#else
#define num 7
#endif

// #define num 7

const float PI = 3.141592653589793;

/* random number between 0 and 1 */
float random(in vec3 scale, in float seed) {
    /* use the fragment position for randomness */
    return fract(sin(dot(gl_FragCoord.xyz + seed, scale)) * 43758.5453 + seed);
}

vec4 crossFade(in vec2 uv, in float dissolve) {
    return texture2D(inputImageTexture, uv).rgba;
}

vec4 directionBlur(sampler2D tex, vec2 resolution, vec2 uv, vec2 directionOfBlur, float intensity)
{
    vec2 pixelStep = 1.0/resolution * intensity;
    float dircLength = length(directionOfBlur);
	pixelStep.x = directionOfBlur.x * 1.0 / dircLength * pixelStep.x;
	pixelStep.y = directionOfBlur.y * 1.0 / dircLength * pixelStep.y;

	vec4 color = vec4(0);
	for(int i = -num; i <= num; i++)
	{
       vec2 blurCoord = uv + pixelStep * float(i);
	   vec2 uvT = vec2(1.0 - abs(abs(blurCoord.x) - 1.0), 1.0 - abs(abs(blurCoord.y) - 1.0));
	   color += texture2D(tex, uvT);
	}
	color /= float(2 * num + 1);	
	return color;
}

void main() {

    float ratio = inputWidth / inputHeight;

    vec2 uv = (u_InvModel * vec4((uv0.x * 2.0 - 1.0) * ratio, uv0.y * 2.0 - 1.0, 0.0, 1.0)).xy;

    uv.x = (uv.x / ratio + 1.0) / 2.0;
    uv.y = (uv.y + 1.0) / 2.0;

#if defined(BLUR_TYPE) && BLUR_TYPE == BLUR_MOTION
	vec2 resolution = vec2(inputWidth,inputHeight);
	vec4 resultColor = directionBlur(inputImageTexture,resolution,uv,blurDirection, blurStep);
	gl_FragColor = vec4(resultColor.rgb, resultColor.a) * step(uv.x, 2.0) * step(uv.y, 2.0) * step(-1.0, uv.x) * step(-1.0, uv.y);

#elif defined(BLUR_TYPE) && BLUR_TYPE == BLUR_SCALE
	vec4 color = vec4(0.0);
    float total = 0.0;
	vec2 toCenter = vec2(0.5, 0.5) - uv;
    float dissolve = 0.5;

    /* randomize the lookup values to hide the fixed number of samples */
    float offset = random(vec3(12.9898, 78.233, 151.7182), 0.0);

    for (int t = 0; t <= num; t++) {
        float percent = (float(t) + offset) / float(num);
        float weight = 4.0 * (percent - percent * percent);

		vec2 curUV = uv + toCenter * percent * blurStep;
        vec2 uvT = vec2(1.0 - abs(abs(curUV.x) - 1.0), 1.0 - abs(abs(curUV.y) - 1.0));
        color += crossFade(uvT, dissolve) * weight;
        // color += crossFade(uvT + toCenter * percent * blurStep, dissolve) * weight;
        total += weight;
    }
    gl_FragColor = color / total * step(uv.x, 2.0) * step(uv.y, 2.0) * step(-1.0, uv.x) * step(-1.0, uv.y);
#else

	// gl_FragColor = texture2D(inputImageTexture, uv);
	gl_FragColor = vec4(1.0, 0.0, 0.0, 1.0);
#endif

    
}
