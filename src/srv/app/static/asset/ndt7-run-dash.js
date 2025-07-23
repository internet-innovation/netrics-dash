const ndt7view = {
  Elements: {
    section: document.getElementById('wifi'),
    interpTxt: document.getElementById('text_wifi_interp'),
    interpTxt1: document.getElementById('text_wifi_interp1'),
    interpTxt2: document.getElementById('text_wifi_interp2'),
    wifiBw: document.getElementById('wifi_bw'),
    ooklaDl: document.getElementById('ookla_dl'),
    errorBusy: document.getElementById('wifi-busy'),
    errorFailure: document.getElementById('wifi-failure'),
  },

  compareSpeeds (a, b) {
    if      (a < b * 0.75) {
      return ['less than', 'bad', 'bad']
    } else if (a > b * 1.25) {
      return ['greater than', 'good', 'good']
    } else {
      return ['similar to', 'not great', 'ok']
    }
  },

  startUpdate () {
    this.preLoading()
    this.clearResults()
  },

  clearResults () {
    this.Elements.section.querySelectorAll('.wifi-result').forEach(elem => {
      elem.classList.add('d-none')
    })
  },

  preLoading () {
    this.Elements.section.querySelectorAll('.loading-done').forEach(elem => {
      elem.classList.remove('loading-done')
      elem.classList.add('loading')
    })
  },

  postLoading () {
    this.Elements.section.querySelectorAll('.loading').forEach(elem => {
      elem.classList.remove('loading')
      elem.classList.add('loading-done')
    })
  },

  TestStatus: {
    incomplete: 0,
    complete: 1,
    busy: 2,
    error: 3,
  },

  updateValues (info, tag, complete) {
    // reset bandwidth gauge
    const bwGauge = this.Elements.wifiBw.parentElement

    bwGauge.classList.remove('bad')
    bwGauge.classList.remove('ok')
    bwGauge.classList.remove('good')
    bwGauge.classList.remove('null')

    if (!info) {
      if (complete && Number.isFinite(complete) && complete > this.TestStatus.complete) {
        const identifier = complete === this.TestStatus.busy ? 'errorBusy' : 'errorFailure'
        const errorNode = this.Elements[identifier]

        errorNode.classList.remove('d-none')

        this.postLoading()

        this.Elements.wifiBw.innerHTML = '&mdash;';

        bwGauge.classList.add('null');
      }

      return
    }

    const elapsed = info.ElapsedTime / 1e06     /* second */
    let speed = info.NumBytes / elapsed         /* B/s    */
    speed *= 8                                     /* bit/s  */
    speed /= 1e06                                  /* Mbit/s */
    speed = speed.toFixed(speed < 10 ? 1 : 0)

    this.Elements.wifiBw.innerHTML = speed;

    const dl_value = parseFloat(this.Elements.ooklaDl.innerHTML);
    const [op, desc, label] = this.compareSpeeds(speed, dl_value);

    bwGauge.classList.add(label);

    if (complete) {
      if (dl_value) {
        this.Elements.interpTxt1.innerHTML = op;
        this.Elements.interpTxt2.innerHTML = desc;
        this.Elements.interpTxt.classList.remove('d-none');
      }

      this.postLoading();
    }
  },

  showFail (testName) {
    console.error('LAN bandwidth test could not be started')
    this.updateValues(null, testName, this.TestStatus.error)
  },

  showBusy (testName) {
    console.info('LAN bandwidth test already running')
    this.updateValues(null, testName, this.TestStatus.busy)
  },
}

const ndt7run = {
  ndtTestHost: window.location.host,
  ndtAssetPath: '/dashboard/asset/ndt/',

  runNdt (testName, viewUpdater) {
    let resolvePromise

    const promise = new Promise(resolver => resolvePromise = resolver)

    ndt7common.run_ndt({
      testHost: this.ndtTestHost,
      assetUrl: this.ndtAssetPath,
      testName: testName,
      updateValues: viewUpdater,
      done: (...args) => resolvePromise(args),
    })

    return promise
  },

  async slotIsOpen () {
    const trialResult = await $.getJSON('trial/', {limit: '1', active: 'on'})
    return trialResult && trialResult.count === 0
  },

  async sendTrial (trial, measurement) {
    if (! measurement || ! Number.isInteger(trial.ts)) {
      console.error('bad trial object %o or results %o', trial, measurement)
      throw TypeError('bad trial object or results')
    }

    return await $.ajax(`trial/${trial.ts}`, {
      method: 'PUT',
      data: {
        size: measurement.NumBytes,
        period: measurement.ElapsedTime.toFixed()
      }
    })
  },

  broadcastRun (measurement, testName) {
    const runEvent = new CustomEvent('ndt7run', {
      detail: {
        measurement: measurement,
        name: testName,
      }
    })

    dispatchEvent(runEvent)
  },

  broadcastUpdate (trial, measurement, testName) {
    const updateEvent = new CustomEvent('ndt7update', {
      detail: {
        measurement: measurement,
        name: testName,
        trial: trial,
      }
    })

    dispatchEvent(updateEvent)
  },

  async runDownload () {
    const startResult = await $.post('trial/?active=on', null, 'json')
    const trial = startResult.inserted

    ndt7view.startUpdate()

    const [measurement, testName] = await this.runNdt(
      'download',
      ndt7view.updateValues.bind(ndt7view),
    )

    this.broadcastRun(measurement, testName)

    if (measurement === null) throw new TypeError("bad result");

    this.sendTrial(trial, measurement)
    .then(() => this.broadcastUpdate(trial, measurement, testName))

    return [measurement, testName]
  },

  async run_download () {
    let error = null
    let failure = 0

    const isOpen = await this.slotIsOpen()

    if (isOpen) {
      try {
        return await this.runDownload()
      } catch (error) {
        failure = (error.hasOwnProperty('status') && error.status === 409) ? 1 : 2
      }
    } else {
      failure = 1
    }

    if (failure === 1) ndt7view.showBusy('download')
    else if (failure === 2) ndt7view.showFail('download')

    throw new Error(`download test failure (${failure})`, {cause: error})
  },

  run_upload () {
    return this.runNdt('upload', ndt7view.updateValues.bind(ndt7view))
  },

  async run_both () {
    result0 = await this.run_download()
    result1 = await this.run_upload()
    return [result0, result1]
  }
}

const ndt7btn = {
  btnId: 'test-network',
  updateInterval: 3000,

  btn: null,
  poll: false,
  timer: null,

  initBtn () {
    'use strict'

    this.btn = document.getElementById(this.btnId)

    this.bindClick()

    this.startPoll()
  },

  bindClick () {
    this.btn.addEventListener('click', this.handleClick.bind(this))
  },
  async handleClick () {
    this.btn.disabled = true

    this.stopPoll()

    try {
      await ndt7run.runDownload()
    } catch (error) {
      if (error.hasOwnProperty('status') && error.status === 409) {
        ndt7view.showBusy('download')
      } else {
        ndt7view.showFail('download')
      }
    }

    this.startPoll()
  },

  startPoll () {
    this.poll = true
    this.continuePoll()
  },
  stopPoll () {
    this.poll = false
    this.clearPoll()
  },
  clearPoll () {
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
  },
  continuePoll () {
    this.clearPoll()

    this.timer = setTimeout(this.handleInterval.bind(this), this.updateInterval)
  },
  async handleInterval () {
    if (! this.poll) return

    const isOpen = await ndt7run.slotIsOpen()
    this.btn.disabled = ! isOpen

    this.continuePoll()
  },
}

if (typeof ndt7conf === 'undefined') {
      ndt7conf = {
          enabled: true
      };
}

if (ndt7conf.enabled) {
  ndt7run.run_download()
  .finally(() => ndt7btn.initBtn())
}
