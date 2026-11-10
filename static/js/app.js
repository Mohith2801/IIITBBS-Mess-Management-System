document.querySelectorAll('.alert').forEach((el) => {
  window.setTimeout(() => {
    if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(el).close();
  }, 6500);
});
const bookingForm = document.getElementById('bookingForm');
if (bookingForm) {
  const boxes = [...bookingForm.querySelectorAll('input[name="meal"]')];
  const total = document.getElementById('total');
  const updateTotal = () => {
    const amount = boxes.filter(b => b.checked).reduce((sum, b) => sum + Number(b.dataset.price || 0), 0);
    total.textContent = `₹${amount}`;
  };
  boxes.forEach(b => b.addEventListener('change', updateTotal));
  updateTotal();
}
