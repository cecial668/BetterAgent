(function(){
  if (window.React && window.ReactDOM) return;
  const FRAGMENT = Symbol('Fragment');
  let rootController = null;

  function flatten(input, out){
    input.forEach(function(item){
      if (Array.isArray(item)) flatten(item, out);
      else if (item === false || item === true || item === null || item === undefined) {}
      else out.push(item);
    });
    return out;
  }

  function createElement(type, props){
    const children = flatten(Array.prototype.slice.call(arguments, 2), []);
    return {type: type, props: props || {}, children: children};
  }

  class Component {
    constructor(props){ this.props = props || {}; this.state = {}; }
    setState(update, cb){
      const next = typeof update === 'function' ? update(this.state, this.props) : update;
      if (next && typeof next === 'object') this.state = Object.assign({}, this.state, next);
      if (rootController) rootController.update();
      if (typeof cb === 'function') setTimeout(cb, 0);
    }
    forceUpdate(cb){
      if (rootController) rootController.update();
      if (typeof cb === 'function') setTimeout(cb, 0);
    }
  }

  function setProp(el, name, value){
    if (name === 'children' || name === 'key' || name === 'ref') return;
    if (name === 'className') { el.setAttribute('class', value || ''); return; }
    if (name === 'htmlFor') { el.setAttribute('for', value || ''); return; }
    if (name === 'style' && value && typeof value === 'object') {
      Object.keys(value).forEach(function(k){ el.style.setProperty(k.startsWith('--') ? k : k.replace(/[A-Z]/g, m => '-' + m.toLowerCase()), value[k]); });
      return;
    }
    if (/^on[A-Z]/.test(name) && typeof value === 'function') {
      el.addEventListener(name.slice(2).toLowerCase(), value);
      return;
    }
    if (name === 'checked' || name === 'defaultChecked') { el.checked = !!value; return; }
    if (name === 'value' || name === 'defaultValue') { if (value !== undefined && value !== null) el.value = value; return; }
    if (name === 'disabled' || name === 'required' || name === 'selected') {
      if (value) el.setAttribute(name, name); else el.removeAttribute(name);
      return;
    }
    if (value === false || value === null || value === undefined) return;
    el.setAttribute(name, String(value));
  }

  function renderVNode(vnode){
    if (Array.isArray(vnode)) {
      const frag = document.createDocumentFragment();
      vnode.forEach(v => frag.appendChild(renderVNode(v)));
      return frag;
    }
    if (vnode === null || vnode === undefined || vnode === false || vnode === true) return document.createTextNode('');
    if (typeof vnode === 'string' || typeof vnode === 'number') return document.createTextNode(String(vnode));
    if (vnode.type === FRAGMENT) {
      const frag = document.createDocumentFragment();
      vnode.children.forEach(c => frag.appendChild(renderVNode(c)));
      return frag;
    }
    if (typeof vnode.type === 'function') {
      if (vnode.type.prototype instanceof Component) {
        const inst = new vnode.type(Object.assign({}, vnode.props, {children: vnode.children}));
        return renderVNode(inst.render());
      }
      return renderVNode(vnode.type(Object.assign({}, vnode.props, {children: vnode.children})));
    }
    const el = document.createElement(vnode.type);
    Object.keys(vnode.props || {}).forEach(k => setProp(el, k, vnode.props[k]));
    vnode.children.forEach(c => el.appendChild(renderVNode(c)));
    return el;
  }

  function createRoot(container){
    const controller = {
      container: container,
      element: null,
      instance: null,
      mounted: false,
      render(element){
        this.element = element;
        if (element && typeof element.type === 'function' && element.type.prototype instanceof Component) {
          if (!this.instance) this.instance = new element.type(Object.assign({}, element.props, {children: element.children}));
          this.instance.props = Object.assign({}, element.props, {children: element.children});
          this.update();
        } else {
          this.update();
        }
      },
      update(){
        if (!this.element) return;
        let vnode;
        const isRootClass = this.instance && this.element.type.prototype instanceof Component;
        if (isRootClass) vnode = this.instance.render();
        else vnode = this.element;
        this.container.innerHTML = '';
        this.container.appendChild(renderVNode(vnode));
        if (isRootClass && !this.mounted && typeof this.instance.componentDidMount === 'function') {
          this.mounted = true;
          setTimeout(() => this.instance.componentDidMount(), 0);
        } else if (isRootClass && this.mounted && typeof this.instance.componentDidUpdate === 'function') {
          setTimeout(() => this.instance.componentDidUpdate(), 0);
        }
      }
    };
    rootController = controller;
    return controller;
  }

  window.React = { createElement, Component, Fragment: FRAGMENT };
  window.ReactDOM = { createRoot };
})();
