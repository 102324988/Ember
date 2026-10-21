import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
export default function Modal({
  title,
  onClose,
  children
}) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement;
    dialog.showModal();
    return () => {
      dialog.close();
      previous?.focus();
    };
  }, []);
  return createPortal(<dialog ref={ref} className="ember-dialog" aria-label={title} onCancel={event => {
    event.preventDefault();
    onClose();
  }} onClick={event => {
    if (event.target === ref.current) onClose();
  }}>
  <div className="dialog-heading">
    <h2>{title}</h2>
    <button onClick={onClose} aria-label={`关闭${title}`}>关闭</button>
  </div>
  <div className="dialog-content">{children}</div>
  </dialog>, document.body);
}
