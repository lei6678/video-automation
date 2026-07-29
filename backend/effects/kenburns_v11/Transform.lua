local exports = exports or {}
local Transform = Transform or {}
Transform.__index = Transform

local function getBezierValue(controls, t)
    local ret = {}
    local xc1 = controls[1]
    local yc1 = controls[2]
    local xc2 = controls[3]
    local yc2 = controls[4]
    ret[1] = 3*xc1*(1-t)*(1-t)*t+3*xc2*(1-t)*t*t+t*t*t
    ret[2] = 3*yc1*(1-t)*(1-t)*t+3*yc2*(1-t)*t*t+t*t*t
    return ret
end

local function getBezierDerivative(controls, t)
    local ret = {}
    local xc1 = controls[1]
    local yc1 = controls[2]
    local xc2 = controls[3]
    local yc2 = controls[4]
    ret[1] = 3*xc1*(1-t)*(1-3*t)+3*xc2*(2-3*t)*t+3*t*t
    ret[2] = 3*yc1*(1-t)*(1-3*t)+3*yc2*(2-3*t)*t+3*t*t
    return ret
end

local function getBezierTfromX(controls, x)
    local ts = 0
    local te = 1
    repeat
        local tm = (ts+te)/2
        local value = getBezierValue(controls, tm)
        if(value[1]>x) then
            te = tm
        else
            ts = tm
        end
    until(te-ts < 0.0001)
    return (te+ts)/2
end

-- Ken Burns progressive zoom-in: 1.0 -> ZOOM_END, smooth ease-in-out
-- Uses cubic bezier (0.25, 0.1, 0.25, 1.0) for natural camera movement feel
local ZOOM_END = 1.12
local BEZIER = {0.25, 0.1, 0.25, 1.0}

local function funcEaseAction1(t, b, c, d)
    t = t/d
    local controls = BEZIER
    local tvalue = getBezierTfromX(controls, t)
    local value = getBezierValue(controls, tvalue)
    return b + c * value[2]
end

local function funcEaseBlurAction1(t, b, c, d)
    t = t/d
    local controls = BEZIER
    local tvalue = getBezierTfromX(controls, t)
    local deriva = getBezierDerivative(controls, tvalue)
    return math.abs(deriva[2] / deriva[1]) * c
end

function Transform.new(construct, ...)
    local self = setmetatable({}, Transform)
    self.material = nil
    self.tweenTransform1 = nil
    self.tweenBlur1 = nil
    self.duration = 0

    -- Single-phase progressive zoom-in: start at 1.0, end at ZOOM_END
    self.startPoint1 = Amaz.Vector3f(0.0, 0.0, 0.0)
    self.startRotate1 = Amaz.Vector3f(0.0, 0.0, 0.0)
    self.startScale1 = Amaz.Vector3f(1.0, 1.0, 1.0)

    self.endPoint1 = Amaz.Vector3f(0.0, 0.0, 0.0)
    self.endRotate1 = Amaz.Vector3f(0.0, 0.0, 0.0)
    self.endScale1 = Amaz.Vector3f(ZOOM_END, ZOOM_END, 1.0)

    self.blurIntensity1 = -0.01
    self.blurType1 = 2  -- zoom blur
    self.blurDirection1 = Amaz.Vector2f(1, 0)
    -- Full duration (single phase)
    self.blurDuration1 = 1.0
    self.moveFunction1 = funcEaseAction1
    self.blurFunction1 = funcEaseBlurAction1

    if construct and Transform.constructor then Transform.constructor(self, ...) end
    return self
end

function Transform:constructor()
end

function Transform:onStart(comp)
    self.vfx = comp.entity.scene:findEntityBy("Blur")
    self.canvas = comp.entity.scene:findEntityBy("Root")
    local transform = comp.entity:getComponent("Transform")
    transform.localPosition = Amaz.Vector3f(0.0, 0.0, 0.0)
    self.material = self.vfx:getComponent("Sprite2DRenderer").material
    self.tweenDirty = true
end

local function checkDirty(self)
    if self.tweenDirty then
        local transform = self.vfx:getComponent("Transform")
        local screenW = Amaz.BuiltinObject:getOutputTextureWidth()
        local screenH = Amaz.BuiltinObject:getOutputTextureHeight()
        local ratio = screenW / screenH

        self.startPoint1 = Amaz.Vector3f(self.startPoint1.x * ratio, self.startPoint1.y, self.startPoint1.z)
        self.endPoint1 = Amaz.Vector3f(self.endPoint1.x * ratio, self.endPoint1.y, self.endPoint1.z)

        -- Single-phase zoom: 1.0 -> ZOOM_END over full duration
        self.tweenTransform1 = self.canvas.scene.tween:fromTo(transform,
            {
                ["localEulerAngle"] = self.startRotate1,
                ["localScale"] = self.startScale1,
                ["localPosition"] = self.startPoint1,
            },
            {
                ["localEulerAngle"] = self.endRotate1,
                ["localScale"] = self.endScale1,
                ["localPosition"] = self.endPoint1,
            },
            self.duration * self.blurDuration1,
            self.moveFunction1,
            nil,
            0.0,
            nil,
            false)

        local material = self.vfx:getComponent("Sprite2DRenderer").material
        material["blurDirection"] = self.blurDirection1
        self.tweenBlur1 = self.canvas.scene.tween:fromTo(self.material,
            {["blurStep"] = self.blurIntensity1/self.duration/self.blurDuration1},
            {["blurStep"] = 0.0},
            self.duration * self.blurDuration1,
            self.blurFunction1,
            nil,
            0.0,
            nil,
            false)

        self.tweenDirty = false
    end
end

local function updateHandle(entity, canvas)
    if entity == nil then
        return
    end
    local animTrans = entity:getComponent("Transform")
    local parentTrans = canvas:getComponent("Transform")
    local userS = parentTrans.localScale
    local userR = parentTrans.localOrientation
    local userT = parentTrans.localPosition
    local animS = animTrans.localScale
    local animR = animTrans.localOrientation
    local animT = animTrans.localPosition
    local mat = parentTrans.localMatrix
    local matA = animTrans.localMatrix
    local userM = parentTrans.localMatrix
    userM:SetTRS(Amaz.Vector3f(0.0, 0.0, 0.0), userR, userS)
    matA:SetTRS(animT, animR, animS)
    matA:AddTranslate(userT)
    animTrans.localMatrix = matA * userM * parentTrans.localMatrix:Invert_Full()
end

function Transform:seek(time)
    checkDirty(self)
    -- Single phase: all time goes to phase 1
    self.material:enableMacro("BLUR_TYPE", self.blurType1)
    self.material["blurDirection"] = self.blurDirection1
    if self.tweenTransform1 then
        self.tweenTransform1:set(time)
    end
    if self.tweenBlur1 then
        self.tweenBlur1:set(time)
    end
    updateHandle(self.vfx, self.canvas)
end

function Transform:setDuration(duration)
    self.duration = duration
    self.tweenDirty = true
end

function Transform:clear()
    self.tweenDirty = true
    if self.tweenTransform1 then
        self.tweenTransform1:set(0)
        self.tweenTransform1:clear()
        self.tweenTransform1 = nil
    end
    if self.tweenBlur1 then
        self.tweenBlur1:set(0)
        self.tweenBlur1:clear()
        self.tweenBlur1 = nil
    end
end

exports.Transform = Transform
return exports
