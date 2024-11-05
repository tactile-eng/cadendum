import math

# See SignalContainer in CadenceOS
class SignalContainer():
	def __init__(self, value: float):
		self.value = value
		self.default = value

	def get(self) -> float:
		return self.value

	def set(self, val: float):
		self.value = val

	def reset(self):
		self.value = self.default

# See Slider in CadenceOS
class Slider():
	def __init__(self, default: float, rateDefault: float, rateRate: float, sliderExp: bool, sliderSCurve: bool, min: float, max: float, strictMinMax: bool):
		self.signal = SignalContainer(default)
		self.rate = SignalContainer(rateDefault)
		self.min = SignalContainer(min)
		self.max = SignalContainer(max)
		self.rateRate = rateRate
		self.sliderExp = sliderExp
		self.sliderSCurve = sliderSCurve
		self.quantize = None
		self.strictMinMax = strictMinMax

	def get(self) -> float:
		return self.signal.get()

	def set(self, val: float):
		self.signal.set(val)

	def getRate(self) -> float:
		return self.rate.get()

	def setRate(self, val: float):
		self.rate.set(val)

	def expOrLog(self, value: float, expOrLog: bool):
		if (self.sliderExp):
			if (expOrLog):
				return math.pow(2, value) - 1
			else:
				return math.log(value + 1) / math.log(2)
		elif (self.sliderSCurve):
			if (value >= 1 or value <= 0): return value
			curvyness = 1.75
			if (expOrLog):
				return 1 / (1 + math.pow(value / (1 - value), -curvyness))
			else:
				if (value == 0.5): return 0.5
				return 1 / (math.pow(1 / value - 1, 1 / curvyness) + 1)
		else:
			return value

	def getNormalised(self):
		return (self.get() - self.min.get()) / (self.max.get() - self.min.get())


	def setNormalized(self, n: float):
		newValue = n * (self.max.get() - self.min.get()) + self.min.get()
		if (self.quantize != None):
			newValue = self.roundValue(newValue)
		if (self.strictMinMax):
			if (newValue < self.min.get()): newValue = self.min.get()
			if (newValue > self.max.get()): newValue = self.max.get()
		self.set(newValue)

	def roundValue(self, n: float) -> float:
		if (self.quantize == None): return n

		min = self.min.get()
		quantize = self.quantize.get()
		rounded = round((n - min) / quantize) * quantize + min

		max = self.max.get()
		if (self.strictMinMax):
			if (rounded < min): rounded = min
			elif (rounded > max): rounded = max
		return rounded

	def round(self):
		if (self.quantize != None):
			self.set(self.roundValue(self.get()))

	def getRateMinQuantize(self) -> float:
		rate = self.getRate()
		if (self.quantize != None and rate < self.quantize.get()):
			rate = self.quantize.get()
		return rate

	def rateSCurve(self, n: float, r: float, min: float, max: float) -> float:
		origNormalized = (n - min) / (max - min)
		rateNormalized = r / (max - min)
		origTransformed = self.expOrLog(origNormalized, False)
		newTransformed = origTransformed + rateNormalized
		newNormalized = self.expOrLog(newTransformed, True)
		return newNormalized * (max - min) + min

	def increase(self):
		n = self.get()

		if (self.sliderExp):
			n = n * self.getRate()
		elif (self.sliderSCurve):
			n = self.rateSCurve(n, self.getRate(), self.min.get(), self.max.get())
		else:
			n = n + self.getRateMinQuantize()

		if (self.strictMinMax and n > self.max.get()):
			n = self.max.get()

		n = self.roundValue(n)

		self.signal.set(n)

	def decrease(self):
		n = self.get()

		if (self.sliderExp):
			n = n / self.getRate()
		elif (self.sliderSCurve):
			n = self.rateSCurve(n, -self.getRate(), self.min.get(), self.max.get())
		else:
			n = n - self.getRateMinQuantize()

		if (self.strictMinMax and n < self.min.get()):
			n = self.min.get()

		n = self.roundValue(n)

		self.signal.set(n)

	def reset(self):
		self.signal.reset()
		self.rate.reset()

	def increaseRate(self):
		rateRate = self.rateRate
		n = self.rate.get()
		if (self.sliderExp):
			self.rate.set((n - 1) * rateRate + 1)
		else:
			self.rate.set(n * rateRate)

	def decreaseRate(self):
		rateRate = self.rateRate
		n = self.rate.get()
		if (self.sliderExp):
			self.rate.set((n - 1) / rateRate + 1)
		else:
			self.rate.set(n / rateRate)

# See CombinedSlider in CadenceOS
class CombinedSlider():
	def __init__(self, sliders: list[Slider]):
		self.sliders = sliders

	def updateSliderRatios(self):
		firstValue = self.sliders[0].get()
		self.sliderRatios = []
		for slider in self.sliders:
			self.sliderRatios.push(slider.get() / firstValue)

	def updateSliders(self):
		firstValue = self.sliders[0].get()
		for i in range(len(self.sliders)):
			self.sliders[i].set(firstValue * self.sliderRatios[i - 1])

	def setNormalized(self, n: float):
		self.updateSliderRatios()
		super.setNormalized(n)
		self.updateSliders()

	def increase(self):
		for slider in self.sliders:
			slider.increase()

	def decrease(self):
		for slider in self.sliders:
			slider.decrease()

	def increaseRate(self):
		for slider in self.sliders:
			slider.increaseRate()

	def decreaseRate(self):
		for slider in self.sliders:
			slider.decreaseRate()

# See PanSlider in CadenceOS
class PanSlider(Slider):
	def __init__(self, default: float, rateDefault: float, rateRate: float, sliderExp: bool, sliderSCurve: bool, min: float, max: float, strictMinMax: bool, zoom):
		super().__init__(default, rateDefault, rateRate, sliderExp, sliderSCurve, min, max, strictMinMax)
		self.zoom = zoom
	def getRate(self) -> float:
		return self.rate.get() / self.zoom()
