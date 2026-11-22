'use strict';

const TARGET = 'com.lptiyu.tanke';
const HEX = '__CERT_HEX__';

function send_msg(message) {
  if (typeof send === 'function') send(message);
  else console.log(JSON.stringify(message));
}

if (!/^(?:[0-9a-fA-F]{2})+$/.test(HEX)) {
  throw new Error('Invalid certificate hex; generate the script with hook.py first');
}

Java.perform(function () {
  const Signature = Java.use('android.content.pm.Signature');
  const official = Signature.$new(HEX);
  const signatures = Java.array('android.content.pm.Signature', [official]);
  // Only SigningInfo objects returned for TARGET are marked. Never spoof every app.
  const marked = Java.use('java.util.WeakHashMap').$new();
  const BooleanClass = Java.use('java.lang.Boolean');
  const hooks = [];
  let patches = 0;

  function patch(info, where) {
    if (info === null || String(info.packageName.value) !== TARGET) return info;
    try {
      info.signatures.value = signatures;
      try {
        const signingInfo = info.signingInfo.value;
        if (signingInfo !== null) marked.put(signingInfo, BooleanClass.TRUE.value);
      } catch (_) { /* Android < 28 has no SigningInfo. */ }
      patches++;
      if (patches <= 5 || patches % 100 === 0) {
        send_msg({ t: 'patch', where: where, count: patches });
      }
    } catch (e) {
      send_msg({ t: 'err', where: where, e: String(e) });
    }
    return info;
  }

  function install(name, fn) {
    try {
      fn();
    } catch (e) {
      send_msg({ t: 'err', what: name, e: String(e) });
    }
  }

  const PM = Java.use('android.app.ApplicationPackageManager');
  ['getPackageInfo', 'getPackageInfoAsUser'].forEach(function (name) {
    install(name, function () {
      PM[name].overloads.forEach(function (overload) {
        const types = overload.argumentTypes.map(function (type) { return type.className; });
        if (types[0] !== 'java.lang.String' ||
            overload.returnType.className !== 'android.content.pm.PackageInfo') return;
        const label = name + '(' + types.join(',') + ')';
        overload.implementation = function () {
          const result = overload.apply(this, arguments);
          return String(arguments[0]) === TARGET ? patch(result, label) : result;
        };
        hooks.push(label);
        send_msg({ t: 'hook', what: label });
      });
    });
  });

  install('SigningInfo', function () {
    const SI = Java.use('android.content.pm.SigningInfo');
    ['getApkContentsSigners', 'getSigningCertificateHistory', 'hasMultipleSigners', 'hasPastSigningCertificates'].forEach(function (name) {
      install('SigningInfo.' + name, function () {
        const overload = SI[name].overload();
        overload.implementation = function () {
          if (marked.containsKey(this)) {
            if (name.indexOf('has') === 0) return false;
            return Java.array('android.content.pm.Signature', [Signature.$new(HEX)]);
          }
          return overload.call(this);
        };
        hooks.push('SigningInfo.' + name);
        send_msg({ t: 'hook', what: 'SigningInfo.' + name });
      });
    });
  });

  install('getInstalledPackages', function () {
    PM.getInstalledPackages.overloads.forEach(function (overload) {
      const label = 'getInstalledPackages(' + overload.argumentTypes.map(function (t) { return t.className; }).join(',') + ')';
      overload.implementation = function () {
        const list = overload.apply(this, arguments);
        if (list !== null) {
          for (let i = 0; i < list.size(); i++) {
            patch(Java.cast(list.get(i), Java.use('android.content.pm.PackageInfo')), label);
          }
        }
        return list;
      };
      hooks.push(label);
      send_msg({ t: 'hook', what: label });
    });
  });

  // Report ready only after installation, not before it.
  send_msg({ t: 'ready', target: TARGET, hooks: hooks.length });
});
